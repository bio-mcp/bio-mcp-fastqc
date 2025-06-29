import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import tempfile

from src.server import {{ToolName}}Server, ServerSettings


@pytest.fixture
def server():
    settings = ServerSettings(
        {{tool_name}}_path="mock_{{tool_name}}",
        temp_dir=tempfile.gettempdir()
    )
    return {{ToolName}}Server(settings)


@pytest.mark.asyncio
async def test_list_tools(server):
    tools = await server.server.list_tools()
    assert len(tools) > 0
    assert any(tool.name == "{{tool_name}}_run" for tool in tools)


@pytest.mark.asyncio
async def test_run_{{tool_name}}_missing_file(server):
    result = await server._run_{{tool_name}}({
        "input_file": "/nonexistent/file.txt"
    })
    assert len(result) == 1
    assert result[0].text.startswith("Input file not found")


@pytest.mark.asyncio
async def test_run_{{tool_name}}_success(server, tmp_path):
    # Create test input file
    input_file = tmp_path / "test_input.txt"
    input_file.write_text("test data")
    
    # Mock subprocess execution
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"output data", b"")
        mock_exec.return_value = mock_process
        
        result = await server._run_{{tool_name}}({
            "input_file": str(input_file)
        })
        
        assert len(result) == 1
        assert result[0].text == "output data"