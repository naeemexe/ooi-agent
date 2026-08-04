# OOI Research Assistant

An OOI-aware layer for the JupyterLab AI chat. It gives a coding agent (`@claude` or
`@opencode`) the knowledge and tools to answer questions about NSF Ocean Observatories
Initiative (OOI) data, resolve the exact access codes for an instrument, check what data
actually exists, and generate notebook cells that fetch, plot, and analyze it.

It has two parts:

- An **MCP server** (`ooi_mcp_server.py`) exposing two tools to the agent:
  - `ooi_lookup` — site code + instrument class → exact node / sensor / method / stream.
  - `ooi_availability` — the real date coverage of a stream, read from the catalog without
    downloading.
- **Notebook helpers** (`ooi_tools.py`): `ooi_fetch`, `ooi_plot`, `ooi_series`. The agent
  writes copy-paste cells that call these, so data and plots stay in the user's kernel.

The agent's instructions live in `CLAUDE.md` / `AGENTS.md`; the OOI knowledge base is in
`context/`.

## Requirements

- Python 3.10+ with [`ooi-data-explorations`](https://anaconda.org/conda-forge/ooi-data-explorations)
  (conda-forge or PyPI) and the packages in `requirements.txt`.
- JupyterLab with the `jupyter-ai` chat extension.
- One agent persona:
  - **`@opencode`** — install [opencode](https://opencode.ai).
  - **`@claude`** — install [Claude Code](https://code.claude.com), plus the ACP adapter:
    `npm install -g @zed-industries/claude-agent-acp`.

## Setup

1. Clone the repository and enter it:
   ```bash
   git clone <your-repo-url> ooi
   cd ooi
   ```

2. Install the dependencies into the environment that has `ooi-data-explorations`:
   ```bash
   pip install -r requirements.txt
   # if ooi-data-explorations is not already installed:
   #   conda install -c conda-forge ooi-data-explorations
   #   (or)  pip install ooi-data-explorations
   ```

3. Register the MCP server with the Jupyter AI chat. Copy the template and set absolute paths:
   ```bash
   cp .jupyter/mcp_settings.json.example .jupyter/mcp_settings.json
   ```
   Edit `.jupyter/mcp_settings.json` so `command` is the Python interpreter of the environment
   above and `args` is the absolute path to `ooi_mcp_server.py`.

4. Launch JupyterLab **from the project folder** and keep chats there. The agent runs with the
   chat file's directory as its working directory, so `CLAUDE.md` / `AGENTS.md` and the MCP
   config are picked up:
   ```bash
   jupyter lab
   ```

5. In the AI chat, address `@claude` or `@opencode`. Approve the `ooi` tools when prompted.

## Access credentials (optional)

The default data source is the public OOI Gold Copy THREDDS server, which needs no credentials.
The `kdata` source reads NetCDF files mounted on an OOI JupyterHub session and needs no
credentials there either.

Credentials are only needed for the OOI M2M API. To enable that path, create a `~/.netrc` file
with API credentials from the [OOI Data Portal](https://ooinet.oceanobservatories.org) user
profile:
```bash
cd ~
touch .netrc
chmod 600 .netrc
cat <<EOT >> .netrc
machine ooinet.oceanobservatories.org
    login <API Username>
    password <API Token>
EOT
```

## Usage

In the chat, describe the data of interest. The agent looks up the exact codes, checks
availability, and returns a notebook cell such as:

```python
from ooi_tools import ooi_availability, ooi_fetch, ooi_plot, ooi_series

ooi_availability("CE02SHSM", "RID27", "02-FLORTD000", "telemetered", "flort_sample")
info = ooi_fetch("CE02SHSM", "RID27", "02-FLORTD000", "telemetered", "flort_sample",
                 start="2024-01-01", stop="2024-06-30", source="thredds")
print(info["science_variables"])
ooi_plot("fluorometric_chlorophyll_a", sites=["CE02SHSM"])
```

`ooi_fetch` returns science variables labeled with long name, units, and OOI data-product
level; raw and engineering columns are hidden. If the requested date range has no data, it
reports the actual coverage instead of downloading the full record. `ooi_series` returns a
time-indexed pandas Series for analysis. `example.ipynb` runs the full sequence.

Run notebooks from the project folder so `import ooi_tools` resolves.

## Repository layout

```
ooi_mcp_server.py     MCP server: ooi_lookup, ooi_availability
ooi_tools.py          notebook helpers: ooi_fetch, ooi_plot, ooi_series
CLAUDE.md / AGENTS.md agent instructions (@claude / @opencode)
context/              OOI knowledge base: arrays, instruments, data products, catalog, param map
.jupyter/             mcp_settings.json (created from the .example template)
example.ipynb         fetch / plot / analyze example
requirements.txt
```
