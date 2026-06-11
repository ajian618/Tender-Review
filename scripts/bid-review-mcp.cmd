@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%"
py -3.12 -m bid_agent.mcp_server
