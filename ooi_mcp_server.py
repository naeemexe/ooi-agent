#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OOI lookup MCP server (stdio transport).

Exposes ONE tool, ooi_lookup, that returns the exact node / sensor / method / stream
for an instrument at an OOI site, read straight from context/m2m_urls.yml.

This is the standalone MCP server that external agents (Claude Code, opencode) connect to
from the Jupyter AI chat. It is intentionally lightweight — the only dependency beyond the
standard library is PyYAML and the mcp SDK. Data fetching and plotting are NOT done here;
the agent writes a copy-paste notebook cell for that (so plots render in the user's kernel).

Run:  python ooi_mcp_server.py     (agents launch it for you via their MCP config)
"""
import os
import yaml
from mcp.server.fastmcp import FastMCP

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, 'context', 'm2m_urls.yml')) as f:
    CATALOG = yaml.safe_load(f)

mcp = FastMCP('ooi')


@mcp.tool()
def ooi_lookup(site: str, instrument: str) -> dict:
    """Get the exact node, sensor, method, and stream codes for an instrument at an OOI site.

    Read straight from OOI's catalog (m2m_urls.yml) — this is ground truth. Use it to turn a
    site code (e.g. CE02SHSM) plus an instrument class (e.g. ctdbp, phsen, flort, dosta, metbk)
    into the exact codes needed to fetch data. Never guess these codes.

    Args:
        site: OOI site code, e.g. CE02SHSM, GI01SUMO, RS01SLBS.
        instrument: instrument class, e.g. ctdbp, phsen, flort, dosta, nutnr, metbk, velpt.

    Returns a dict with the matching node/sensor/depth/location and the available
    method->stream options; or, if the instrument isn't at that site, the list of
    instrument classes that ARE there.
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
                options.append({
                    'node': instr['node'],
                    'sensor': instr['sensor'],
                    'depth_m': instr.get('mindepth'),
                    'location': assembly.get('name', assembly.get('type')),
                    'methods_and_streams': instr.get('stream', {}),
                })

    if not options:
        return {'error': f"No '{ins}' at {s}.",
                'instruments_at_this_site': sorted(instruments_here)}
    return {'site': s, 'instrument': ins, 'options': options}


if __name__ == '__main__':
    mcp.run()   # stdio transport by default
