#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OOI notebook helpers: ooi_fetch + ooi_plot.

These are the two functions the assistant's copy-paste cells call. They run in YOUR
notebook kernel (not in the MCP server), so the data stays in your session and plots
render inline.

    from ooi_tools import ooi_fetch, ooi_plot
    ooi_fetch("CE02SHSM", "RID27", "03-CTDBPC000", "telemetered",
              "ctdbp_cdef_dcl_instrument", start="2024-05-01", stop="2024-06-01")
    ooi_plot("sea_water_temperature", sites=["CE02SHSM"])

(The exact node/sensor/method/stream come from the `ooi_lookup` MCP tool — see
ooi_mcp_server.py. This file does not do lookups.)
"""
import os
import re
import warnings

os.environ['TQDM_DISABLE'] = '1'   # suppress tqdm widget errors in Jupyter

import matplotlib.pyplot as plt

from ooi_data_explorations.common import list_files, parallel_process_files, merge_frames

# Base URL of the OOI Gold Copy THREDDS catalog (public, no auth).
_GC_URL = ('https://thredds.dataexplorer.oceanobservatories.org/thredds/'
           'catalog/ooigoldcopy/public/')

# Datasets fetched this session, keyed by site code (so we can plot/compare them).
DATASETS = {}


def _file_dates(filename):
    """Pull the (start, end) YYYYMMDD dates out of a Gold Copy filename, or (None, None)."""
    m = re.search(r'_(\d{8})T\d{6}[^-]*-(\d{8})T\d{6}', filename)
    return (m.group(1), m.group(2)) if m else (None, None)


def ooi_fetch(site, node, sensor, method, stream, start=None, stop=None, max_files=40):
    """Download data for ONE instrument from OOI Gold Copy, keep it, and list its variables.

    Only files for this exact stream are used (co-located sensors sharing the node are
    excluded), only files whose dates overlap [start, stop] are downloaded, and the number
    of files is capped so a fetch stays fast. Dates are 'YYYY-MM-DD' strings.
    """
    site = site.upper()
    url = _GC_URL + f'{site}-{node}-{sensor}-{method}-{stream}/catalog.html'

    # 1) List the catalog (fast — no download yet). The tag pins this exact sensor+stream,
    #    so we never pick up files from a different sensor on the same node.
    try:
        files = sorted(list_files(url, rf'.*{sensor}-{method}-{stream}.*\.nc$'))
    except Exception as e:
        return {'error': f"Could not read the catalog: {e}"}
    if not files:
        return {'error': f"No files for {site} {node} {sensor} {method} {stream}. "
                         f"Re-check the codes from ooi_lookup, or try another method "
                         f"(recovered_host is often available when telemetered isn't)."}

    # 2) Keep only files whose date range overlaps the request.
    lo = (start or '0000-01-01').replace('-', '')
    hi = (stop or '9999-12-31').replace('-', '')
    wanted = [f for f in files
              if _file_dates(f)[0] is None
              or (_file_dates(f)[0] <= hi and _file_dates(f)[1] >= lo)]
    note = None
    if not wanted:
        wanted, note = files, f"No files within {start}..{stop}; using the most recent data instead."

    # 3) Cap the count (keep the most recent) so the download stays quick.
    n_total = len(wanted)
    if n_total > max_files:
        wanted = wanted[-max_files:]
        note = (f"Fetched the {max_files} most recent files of {n_total} in range (telemetered "
                f"data splits into many small files). Narrow the dates, or use recovered_host, "
                f"for a longer span.")

    # 4) Download just those files and merge.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            frames = parallel_process_files(wanted, gc='GC', use_dask=False,
                                            desc=f'Downloading {len(wanted)} {stream} file(s)')
            ds = merge_frames(frames)
    except Exception as e:
        return {'error': f"Could not load data: {e}"}
    if ds is None or 'time' not in ds or ds.time.size == 0:
        return {'error': f"Downloaded files but found no records for {site} {stream}."}

    ds = ds.sortby('time')
    if start or stop:                      # precise trim (files can extend past the window)
        trimmed = ds.sel(time=slice(start, stop))
        if trimmed.time.size:
            ds = trimmed

    DATASETS[site] = ds

    # Science variables = drop the QC/flag/metadata columns, keep the real measurements.
    skip = ('_qc_', '_qartod_', '_quality_flag')
    variables = [v for v in sorted(ds.data_vars)
                 if not any(s in v for s in skip)
                 and v not in ('deployment', 'station_name')]

    result = {
        'site': site,
        'records': int(ds.time.size),
        'files_used': len(wanted),
        'time_start': str(ds.time.values[0])[:10],
        'time_end': str(ds.time.values[-1])[:10],
        'variables': variables,
    }
    if note:
        result['note'] = note
    return result


def ooi_plot(variable, sites=None, title=None):
    """Plot ds[variable] for one or more fetched sites on the same axes (renders inline)."""
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
        return {'error': f"'{variable}' not found in fetched data for {sites}. "
                         f"Fetch the data first, or check the variable name."}

    plt.title(title or variable.replace('_', ' ').title())
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()
    return {'plotted_variable': variable, 'sites': plotted}
