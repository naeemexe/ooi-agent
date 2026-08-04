#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OOI MCP server (stdio transport).

Tools:
    ooi_lookup(site, instrument)                       -> node/sensor/method/stream
    ooi_availability(site, node, sensor, method, stream) -> date coverage of a stream

Launched as a subprocess by the agent via its MCP configuration. Dependencies are
PyYAML, requests, and the mcp SDK. Data download, plotting, and analysis are handled
by ooi_tools.py in the notebook kernel, not here.
"""
import os
import re
import yaml
import requests
from mcp.server.fastmcp import FastMCP

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, 'context', 'm2m_urls.yml')) as f:
    CATALOG = yaml.safe_load(f)

_GC_URL = ('https://thredds.dataexplorer.oceanobservatories.org/thredds/'
           'catalog/ooigoldcopy/public/')

mcp = FastMCP('ooi')


@mcp.tool()
def ooi_lookup(site: str, instrument: str) -> dict:
    """Resolve an instrument at a site to its exact node, sensor, method, and stream codes.

    Reads OOI's catalog (m2m_urls.yml). These codes must not be guessed.

    Args:
        site: OOI site code, e.g. CE02SHSM, GI01SUMO, RS01SLBS.
        instrument: instrument class, e.g. ctdbp, phsen, flort, dosta, nutnr, metbk, velpt.

    Returns the matching node/sensor/depth/location and the available method->stream
    options, or the instrument classes present at the site if there is no match.
    """
    s = site.upper()
    ins = instrument.lower()
    if s not in CATALOG:
        return {'error': f"'{s}' is not a known OOI site code."}

    options, instruments_here = [], set()
    for assembly in CATALOG[s].get('assembly', []):
        for instr in assembly.get('instrument', []):
            instruments_here.add(instr['class'])
            if instr['class'] == ins:
                # some methods list several streams; the first is the primary one
                streams = {m: (v[0] if isinstance(v, list) else v)
                           for m, v in (instr.get('stream') or {}).items()}
                options.append({
                    'node': instr['node'],
                    'sensor': instr['sensor'],
                    'depth_m': instr.get('mindepth'),
                    'location': assembly.get('name', assembly.get('type')),
                    'methods_and_streams': streams,
                })

    if not options:
        return {'error': f"No '{ins}' at {s}.",
                'instruments_at_this_site': sorted(instruments_here)}
    return {'site': s, 'instrument': ins, 'options': options}


@mcp.tool()
def ooi_availability(site: str, node: str, sensor: str, method: str, stream: str) -> dict:
    """Report the date coverage of a stream on the Gold Copy THREDDS server.

    Lists the catalog filenames (which embed dates) without downloading, and returns the
    first and last dates available plus the file count. A requested period outside this
    range has no data; the actual coverage, another delivery method (recovered_host /
    recovered_inst), or the kdata source are the alternatives.

    Args:
        site, node, sensor, method, stream: codes from ooi_lookup.

    Returns available_from / available_to (YYYY-MM-DD) and n_files, or status
    'not_found' / 'error'.
    """
    ds_id = f'{site.upper()}-{node}-{sensor}-{method}-{stream}'
    try:
        html = requests.get(_GC_URL + ds_id + '/catalog.html', timeout=30).text
    except Exception as e:
        return {'status': 'error', 'message': f"Could not read the THREDDS catalog: {e}"}

    tag = re.compile(rf'{re.escape(sensor)}-{re.escape(method)}-{re.escape(stream)}.*?\.nc')
    files = tag.findall(html)
    if not files:
        return {'status': 'not_found',
                'message': f"No THREDDS files for {ds_id}. Check the codes, or try another "
                           f"delivery method (recovered methods sometimes exist when "
                           f"telemetered does not, and the reverse)."}

    dates = [(m.group(1), m.group(2)) for f in files
             for m in [re.search(r'_(\d{8})T\d{6}[^-]*-(\d{8})T\d{6}', f)] if m]
    if not dates:
        return {'status': 'ok', 'n_files': len(files),
                'note': 'files found but dates not parseable from names'}
    first, last = min(d[0] for d in dates), max(d[1] for d in dates)
    fmt = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return {'status': 'ok', 'n_files': len(files),
            'available_from': fmt(first), 'available_to': fmt(last)}


if __name__ == '__main__':
    mcp.run()
