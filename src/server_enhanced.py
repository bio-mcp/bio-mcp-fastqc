"""
Enhanced FastQC MCP server with intelligent tool detection.

This server can automatically detect and use FastQC/MultiQC from:
- Native installations (PATH)
- Environment Modules
- Lmod modules
- Singularity containers
- Docker containers
"""

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, ErrorContent
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .tool_detection import ToolDetector, ToolConfig, ExecutionMode, ToolInfo

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = Field(default=10_000_000_000, description="Maximum input file size in bytes")  # 10GB
    temp_dir: Optional[str] = Field(default=None, description="Temporary directory for processing")
    timeout: int = Field(default=1800, description="Command timeout in seconds")  # 30 minutes
    
    # Tool execution mode settings
    execution_mode: Optional[str] = None
    preferred_modes: str = "native,module,lmod,singularity,docker"
    module_names: str = "fastqc,FastQC"
    container_image: str = "quay.io/biocontainers/fastqc:0.12.1"
    
    class Config:
        env_prefix = "BIO_MCP_"


class FastQCServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-fastqc")
        self.detector = ToolDetector(logger)
        self.tool_config = ToolConfig.from_env()
        self.fastqc_info = None
        self.multiqc_info = None
        self._setup_handlers()
        
    async def _detect_tool(self, tool_name: str) -> ToolInfo:
        """Detect the best available execution mode for a tool."""
        # Parse settings
        force_mode = None
        if self.settings.execution_mode:
            try:
                force_mode = ExecutionMode(self.settings.execution_mode.lower())
            except ValueError:
                logger.warning(f"Invalid execution mode: {self.settings.execution_mode}")
        
        preferred_modes = []
        for mode_str in self.settings.preferred_modes.split(","):
            try:
                mode = ExecutionMode(mode_str.strip().lower())
                preferred_modes.append(mode)
            except ValueError:
                logger.warning(f"Invalid preferred mode: {mode_str}")
        
        # Tool-specific module names
        if tool_name == "fastqc":
            module_names = [name.strip() for name in self.settings.module_names.split(",")]
        else:  # multiqc
            module_names = ["multiqc", "MultiQC"]
        
        # Detect tool
        tool_info = self.detector.detect_tool(
            tool_name=tool_name,
            module_names=module_names,
            container_image=self.settings.container_image,
            preferred_modes=preferred_modes or None,
            force_mode=force_mode
        )
        
        return tool_info
    
    async def _get_fastqc_info(self) -> ToolInfo:
        """Get FastQC tool information."""
        if self.fastqc_info is None:
            self.fastqc_info = await self._detect_tool("fastqc")
        return self.fastqc_info
    
    async def _get_multiqc_info(self) -> ToolInfo:
        """Get MultiQC tool information."""
        if self.multiqc_info is None:
            self.multiqc_info = await self._detect_tool("multiqc")
        return self.multiqc_info
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="fastqc",
                    description="Quality control analysis of high-throughput sequencing data with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string",
                                "description": "Path to FASTQ/SAM/BAM file"
                            },
                            "output_format": {
                                "type": "string",
                                "enum": ["html", "zip", "both"],
                                "default": "both",
                                "description": "Output format"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 1,
                                "description": "Number of threads"
                            },
                            "quiet": {
                                "type": "boolean",
                                "default": False,
                                "description": "Suppress progress messages"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="multiqc",
                    description="Aggregate results from multiple FastQC reports with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_dir": {
                                "type": "string",
                                "description": "Directory containing FastQC reports"
                            },
                            "report_title": {
                                "type": "string",
                                "description": "Report title"
                            },
                            "comment": {
                                "type": "string",
                                "description": "Report comment"
                            }
                        },
                        "required": ["input_dir"]
                    }
                ),
                Tool(
                    name="fastqc_info",
                    description="Get information about FastQC tool detection and execution mode",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent | ErrorContent]:
            if name == "fastqc":
                return await self._run_fastqc(arguments)
            elif name == "multiqc":
                return await self._run_multiqc(arguments)
            elif name == "fastqc_info":
                return await self._get_tool_info()
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _get_tool_info(self) -> list[TextContent]:
        """Get information about tool detection."""
        fastqc_info = await self._get_fastqc_info()
        multiqc_info = await self._get_multiqc_info()
        
        info = {
            "fastqc": {
                "execution_mode": fastqc_info.mode.value,
                "available": fastqc_info.mode != ExecutionMode.UNAVAILABLE,
                "path": fastqc_info.path,
                "version": fastqc_info.version,
                "module_name": fastqc_info.module_name,
                "container_image": fastqc_info.container_image
            },
            "multiqc": {
                "execution_mode": multiqc_info.mode.value,
                "available": multiqc_info.mode != ExecutionMode.UNAVAILABLE,
                "path": multiqc_info.path,
                "version": multiqc_info.version,
                "module_name": multiqc_info.module_name,
                "container_image": multiqc_info.container_image
            },
            "settings": {
                "execution_mode": self.settings.execution_mode,
                "preferred_modes": self.settings.preferred_modes.split(","),
                "module_names": self.settings.module_names.split(","),
                "container_image": self.settings.container_image
            }
        }
        
        return [TextContent(text=json.dumps(info, indent=2))]
    
    async def _execute_tool_command(self, tool_name: str, tool_args: list[str], tmpdir: str) -> tuple[bytes, bytes, int]:
        """Execute a tool command with intelligent tool detection."""
        # Detect tool
        if tool_name == "fastqc":
            tool_info = await self._get_fastqc_info()
        else:  # multiqc
            tool_info = await self._get_multiqc_info()
            
        if tool_info.mode == ExecutionMode.UNAVAILABLE:
            raise RuntimeError(f"{tool_name} is not available in any execution mode")
        
        # Build complete command
        cmd = self.detector.get_execution_command(tool_info, tool_args)
        
        logger.info(f"Executing {tool_name} via {tool_info.mode.value}: {' '.join(cmd)}")
        
        # Execute command
        if tool_info.mode in [ExecutionMode.MODULE, ExecutionMode.LMOD]:
            # Module commands need to be executed in shell
            shell_cmd = " ".join(cmd)
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir
            )
        else:
            # Direct execution for native, container modes
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir
            )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=self.settings.timeout
        )
        
        return stdout, stderr, process.returncode
    
    async def _run_fastqc(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run FastQC with intelligent tool detection."""
        try:
            input_file = Path(arguments["input_file"])
            if not input_file.exists():
                return [ErrorContent(text=f"Input file not found: {input_file}")]
            
            if input_file.stat().st_size > self.settings.max_file_size:
                return [ErrorContent(text=f"File too large. Maximum size: {self.settings.max_file_size} bytes")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                # Copy input file to temp directory
                temp_input = Path(tmpdir) / input_file.name
                temp_input.write_bytes(input_file.read_bytes())
                
                # Build FastQC arguments
                tool_args = []
                
                # Output directory
                tool_args.extend(["-o", tmpdir])
                
                # Threads
                tool_args.extend(["-t", str(arguments.get("threads", 1))])
                
                # Quiet mode
                if arguments.get("quiet", False):
                    tool_args.append("-q")
                
                # Output format
                output_format = arguments.get("output_format", "both")
                if output_format == "html":
                    tool_args.append("--nozip")
                elif output_format == "zip":
                    tool_args.append("--nohtml")
                # both is default
                
                # Input file
                tool_args.append(str(temp_input))
                
                # Execute command
                stdout, stderr, returncode = await self._execute_tool_command("fastqc", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"FastQC failed: {stderr.decode()}")]
                
                # Find output files
                output_files = []
                for file in Path(tmpdir).glob("*"):
                    if file.is_file() and file.name != temp_input.name:
                        output_files.append(file)
                
                # Return results
                result_text = f"FastQC completed successfully\\n"
                result_text += f"Generated {len(output_files)} output files:\\n"
                for file in output_files:
                    result_text += f"- {file.name} ({file.stat().st_size} bytes)\\n"
                
                return [TextContent(text=result_text)]
                
        except Exception as e:
            logger.error(f"Error running FastQC: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_multiqc(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run MultiQC with intelligent tool detection."""
        try:
            input_dir = Path(arguments["input_dir"])
            if not input_dir.exists():
                return [ErrorContent(text=f"Input directory not found: {input_dir}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                # Build MultiQC arguments
                tool_args = []
                
                # Output directory
                tool_args.extend(["-o", tmpdir])
                
                # Report title
                if arguments.get("report_title"):
                    tool_args.extend(["--title", arguments["report_title"]])
                
                # Comment
                if arguments.get("comment"):
                    tool_args.extend(["--comment", arguments["comment"]])
                
                # Input directory
                tool_args.append(str(input_dir))
                
                # Execute command
                stdout, stderr, returncode = await self._execute_tool_command("multiqc", tool_args, tmpdir)
                
                if returncode != 0:
                    return [ErrorContent(text=f"MultiQC failed: {stderr.decode()}")]
                
                # Find output files
                output_files = []
                for file in Path(tmpdir).glob("*"):
                    if file.is_file():
                        output_files.append(file)
                
                # Return results
                result_text = f"MultiQC completed successfully\\n"
                result_text += f"Generated {len(output_files)} output files:\\n"
                for file in output_files:
                    result_text += f"- {file.name} ({file.stat().st_size} bytes)\\n"
                
                return [TextContent(text=result_text)]
                
        except Exception as e:
            logger.error(f"Error running MultiQC: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream)


async def main():
    logging.basicConfig(level=logging.INFO)
    server = FastQCServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())