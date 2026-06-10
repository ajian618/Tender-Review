@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%"
if "%BID_AGENT_BASE_URL%"=="" set "BID_AGENT_BASE_URL=http://127.0.0.1:8000"
py -3.12 -m bid_agent.mcp_server
