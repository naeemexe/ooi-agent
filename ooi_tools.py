#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OOI data access and analysis helpers for notebook use.

Functions
    ooi_availability(site, node, sensor, method, stream, source)
        Date coverage of a stream, read from the catalog without downloading.
    ooi_fetch(site, node, sensor, method, stream, start, stop, source, max_files)
        Download one instrument's data and return its science variables.
    ooi_plot(variable, sites, title)
        Line plot of a variable across one or more fetched sites.
    ooi_series(variable, site)
        Time-indexed pandas Series for a variable, cleaned for analysis.

Codes (node, sensor, method, stream) come from the ooi_lookup MCP tool.
The two data sources are "thredds" (public Gold Copy server) and "kdata"
(NetCDF store mounted on an OOI JupyterHub session).
"""
import os
import re
import csv
import glob
import warnings

os.environ['TQDM_DISABLE'] = '1'

import matplotlib.pyplot as plt

from ooi_data_explorations.common import (
    list_files, parallel_process_files, merge_frames, kdata_collect_from_file_list,
)

_DIR = os.path.dirname(os.path.abspath(__file__))
_GC_URL = ('https://thredds.dataexplorer.oceanobservatories.org/thredds/'
           'catalog/ooigoldcopy/public/')
_KDATA_ROOT = os.path.join(os.path.expanduser('~'), 'ooi', 'kdata')

# netcdf_name -> {longname, units, level, standardname} from OOI ParameterDefs.
# level L1/L2 are science products; L0 is raw counts / engineering.
PARAM_MAP = {}
try:
    with open(os.path.join(_DIR, 'context', 'parameter_map.csv'), newline='') as f:
        for row in csv.DictReader(f):
            PARAM_MAP[row['netcdf_name']] = row
except FileNotFoundError:
    pass

# Datasets fetched this session, keyed by site code.
DATASETS = {}


def _file_dates(name):
    """Return (start, end) YYYYMMDD strings from an OOI filename, or (None, None)."""
    m = re.search(r'_(\d{8})T\d{6}[^-]*-(\d{8})T\d{6}', name)
    return (m.group(1), m.group(2)) if m else (None, None)


def _pretty(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else d


def _list_source_files(site, node, sensor, method, stream, source):
    """List a stream's files without downloading. The tag pins this exact
    sensor+stream so files from a co-located sensor are excluded."""
    ds_id = f'{site}-{node}-{sensor}-{method}-{stream}'
    tag = rf'.*{sensor}-{method}-{stream}.*\.nc$'
    if source == 'kdata':
        d = os.path.join(_KDATA_ROOT, ds_id)
        return sorted(f for f in glob.glob(os.path.join(d, '*.nc')) if re.search(tag, f))
    return sorted(list_files(_GC_URL + ds_id + '/catalog.html', tag))


def _coverage(files):
    """Return (first, last) YYYYMMDD across a file list, ignoring undated names."""
    dates = [d for f in files for d in [_file_dates(f)] if d[0]]
    if not dates:
        return None, None
    return min(d[0] for d in dates), max(d[1] for d in dates)


def _science_vars(ds):
    """Split dataset variables into labeled science variables and hidden
    engineering variables.

    Science = OOI data-product level L1/L2, or a variable with a CF standard_name
    and physical units. Hidden = raw counts (L0), timestamps, wavelengths, QC
    flags, and coordinates.
    """
    skip = ('_qc_', '_qartod_', '_quality_flag')
    meta = {'deployment', 'station_name', 'lat', 'lon', 'z'}
    science, other = {}, []
    for v in sorted(ds.data_vars):
        if v in meta or any(s in v for s in skip):
            continue
        if v.endswith('_timestamp') or 'wavelength' in v:
            other.append(v)
            continue
        info = PARAM_MAP.get(v, {})
        level = info.get('level', '')
        units = info.get('units') or ds[v].attrs.get('units', '')
        std = ds[v].attrs.get('standard_name', '')
        is_science = level in ('L1', 'L2') or (std and units and units not in ('counts', '1'))
        if not is_science:
            other.append(v)
            continue
        long = info.get('longname') or ds[v].attrs.get('long_name', v)
        science[v] = long + (f" ({units})" if units else "") + (f" [{level}]" if level else "")
    return science, other


def ooi_availability(site, node, sensor, method, stream, source='thredds'):
    """Return the date coverage of a stream without downloading data.

    Returns available_from / available_to (YYYY-MM-DD) and n_files, or a status
    of 'not_found' / 'error'.
    """
    site = site.upper()
    try:
        files = _list_source_files(site, node, sensor, method, stream, source)
    except Exception as e:
        return {'status': 'error', 'message': f"Could not read the {source} catalog: {e}"}
    if not files:
        msg = f"No {source} files for {site} {node} {sensor} {method} {stream}."
        if source == 'kdata':
            msg += f" ({os.path.join(_KDATA_ROOT, site)}... not present — kdata is an OOI JupyterHub mount.)"
        return {'status': 'not_found', 'message': msg}
    first, last = _coverage(files)
    return {'status': 'ok', 'source': source, 'n_files': len(files),
            'available_from': _pretty(first), 'available_to': _pretty(last)}


def ooi_fetch(site, node, sensor, method, stream,
              start=None, stop=None, source='thredds', max_files=40):
    """Download one instrument's data from `source` and return its science variables.

    Only files whose dates overlap [start, stop] are downloaded, capped at
    max_files (most recent). If the requested range has no data, returns status
    'no_data_in_range' with the actual coverage instead of downloading the full
    record. Dates are 'YYYY-MM-DD' strings; source is 'thredds' or 'kdata'.
    """
    site = site.upper()
    try:
        files = _list_source_files(site, node, sensor, method, stream, source)
    except Exception as e:
        return {'status': 'error', 'message': f"Could not read the {source} catalog: {e}"}
    if not files:
        return {'status': 'not_found',
                'message': f"No {source} files for {site} {node} {sensor} {method} {stream}. "
                           f"Check the codes, try another method, or the other source."}

    lo = (start or '00000000').replace('-', '')
    hi = (stop or '99999999').replace('-', '')
    wanted = [f for f in files
              if _file_dates(f)[0] is None
              or (_file_dates(f)[0] <= hi and _file_dates(f)[1] >= lo)]

    if not wanted and (start or stop):
        first, last = _coverage(files)
        return {'status': 'no_data_in_range',
                'requested': f"{start or '...'} to {stop or '...'}",
                'available_from': _pretty(first), 'available_to': _pretty(last),
                'message': (f"{site} {stream} has no data in {start}..{stop}; coverage is "
                            f"{_pretty(first)} to {_pretty(last)}. Choose a period in that range, "
                            f"another method (recovered_host/recovered_inst), or the other source.")}
    if not wanted:
        wanted = files

    note = None
    n_total = len(wanted)
    if n_total > max_files:
        wanted = wanted[-max_files:]
        note = (f"{max_files} most recent of {n_total} files in range; narrow the dates or use "
                f"recovered_host for a longer continuous span.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            if source == 'kdata':
                ds = kdata_collect_from_file_list(wanted)     # already merged
            else:
                frames = parallel_process_files(wanted, gc='GC', use_dask=False,
                                                desc=f'Downloading {len(wanted)} {stream} file(s)')
                ds = merge_frames(frames)
    except Exception as e:
        return {'status': 'error', 'message': f"Could not load data: {e}"}
    if ds is None or 'time' not in ds or ds.time.size == 0:
        return {'status': 'error', 'message': f"Files found but no records for {site} {stream}."}

    ds = ds.sortby('time')
    if start or stop:
        trimmed = ds.sel(time=slice(start, stop))
        if trimmed.time.size:
            ds = trimmed
    DATASETS[site] = ds

    science, other = _science_vars(ds)
    result = {
        'status': 'ok', 'source': source, 'site': site,
        'records': int(ds.time.size), 'files_used': len(wanted),
        'time_start': str(ds.time.values[0])[:10], 'time_end': str(ds.time.values[-1])[:10],
        'science_variables': science,
        'other_variables_hidden': len(other),
    }
    if note:
        result['note'] = note
    return result


def ooi_plot(variable, sites=None, title=None):
    """Line plot of a variable across one or more fetched sites."""
    sites = [s.upper() for s in sites] if sites else list(DATASETS)
    plt.figure(figsize=(12, 4))
    plotted = []
    for site in sites:
        ds = DATASETS.get(site)
        if ds is not None and variable in ds:
            ds[variable].plot(label=site)
            plotted.append(site)
    if not plotted:
        plt.close()
        return {'status': 'error',
                'message': f"'{variable}' not in fetched data for {sites}. Fetch first, or check the name."}
    lab = PARAM_MAP.get(variable, {}).get('longname', variable.replace('_', ' ').title())
    plt.title(title or lab)
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout(); plt.show()
    return {'status': 'ok', 'plotted_variable': variable, 'sites': plotted}


def ooi_series(variable, site=None):
    """Return a time-indexed pandas Series for a variable, with fill values dropped.

    Supports analysis such as s.resample('1M').mean(), s.groupby(s.index.month).mean(),
    or s.idxmax(). Defaults to the most recently fetched site.
    """
    site = (site or (list(DATASETS)[-1] if DATASETS else '')).upper()
    ds = DATASETS.get(site)
    if ds is None:
        raise ValueError(f"No data fetched for {site!r}. Run ooi_fetch first.")
    if variable not in ds:
        raise ValueError(f"{variable!r} not in {site}. Available: {list(_science_vars(ds)[0])}")
    s = ds[variable].to_series().dropna()
    s = s[(s > -1e30) & (s < 1e30)]
    s.name = variable
    return s
