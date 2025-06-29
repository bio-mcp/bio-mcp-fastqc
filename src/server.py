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


logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = Field(default=10_000_000_000, description="Maximum input file size in bytes")  # 10GB for large FASTQ files
    temp_dir: Optional[str] = Field(default=None, description="Temporary directory for processing")
    timeout: int = Field(default=1800, description="Command timeout in seconds")  # 30 minutes
    fastqc_path: str = Field(default="fastqc", description="Path to FastQC executable")
    multiqc_path: str = Field(default="multiqc", description="Path to MultiQC executable")
    
    class Config:
        env_prefix = "BIO_MCP_"


class FastQCServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-fastqc")
        self._setup_handlers()
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="fastqc_single",
                    description="Run FastQC quality control on a single FASTQ/FASTA file",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_file": {
                                "type": "string", 
                                "description": "Path to FASTQ or FASTA file"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 1,
                                "description": "Number of threads to use"
                            },
                            "contaminants": {
                                "type": "string",
                                "description": "Path to contaminants file"
                            },
                            "adapters": {
                                "type": "string",
                                "description": "Path to adapters file"
                            },
                            "limits": {
                                "type": "string",
                                "description": "Path to limits file"
                            }
                        },
                        "required": ["input_file"]
                    }
                ),
                Tool(
                    name="fastqc_batch",
                    description="Run FastQC on multiple files in a directory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_dir": {
                                "type": "string",
                                "description": "Directory containing FASTQ/FASTA files"
                            },
                            "file_pattern": {
                                "type": "string",
                                "default": "*.fastq*",
                                "description": "File pattern to match (e.g., '*.fastq.gz')"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 4,
                                "description": "Number of threads to use"
                            }
                        },
                        "required": ["input_dir"]
                    }
                ),
                Tool(
                    name="multiqc_report",
                    description="Generate MultiQC report from directory of analysis results",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input_dir": {
                                "type": "string",
                                "description": "Directory containing FastQC and other analysis results"
                            },
                            "title": {
                                "type": "string",
                                "description": "Title for the report"
                            },
                            "comment": {
                                "type": "string",
                                "description": "Comment to add to the report"
                            },
                            "template": {
                                "type": "string",
                                "enum": ["default", "simple", "sections", "gathered"],
                                "default": "default",
                                "description": "Report template to use"
                            }
                        },
                        "required": ["input_dir"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent | ErrorContent]:
            handlers = {
                "fastqc_single": self._run_fastqc_single,
                "fastqc_batch": self._run_fastqc_batch,
                "multiqc_report": self._run_multiqc,
            }
            
            handler = handlers.get(name)
            if handler:
                return await handler(arguments)
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _run_fastqc_single(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_path = Path(arguments["input_file"])
            if not input_path.exists():
                return [ErrorContent(text=f"Input file not found: {input_path}")]
            
            if input_path.stat().st_size > self.settings.max_file_size:
                return [ErrorContent(text=f"File too large. Maximum size: {self.settings.max_file_size} bytes")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_dir = Path(tmpdir) / "fastqc_output"
                output_dir.mkdir()
                
                # Build FastQC command
                cmd = [
                    self.settings.fastqc_path,
                    "--outdir", str(output_dir),
                    "--threads", str(arguments.get("threads", 1)),
                    "--extract"  # Extract zip files for easier access
                ]
                
                # Add optional parameters
                if arguments.get("contaminants"):
                    cmd.extend(["--contaminants", arguments["contaminants"]])
                if arguments.get("adapters"):
                    cmd.extend(["--adapters", arguments["adapters"]])
                if arguments.get("limits"):
                    cmd.extend(["--limits", arguments["limits"]])
                
                cmd.append(str(input_path))
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return [ErrorContent(text=f"FastQC timed out after {self.settings.timeout} seconds")]
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"FastQC failed: {stderr.decode()}")]
                
                # Parse results
                results = await self._parse_fastqc_results(output_dir, input_path.stem)
                return [TextContent(text=results)]
                
        except Exception as e:
            logger.error(f"Error running FastQC: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_fastqc_batch(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_dir = Path(arguments["input_dir"])
            if not input_dir.exists():
                return [ErrorContent(text=f"Input directory not found: {input_dir}")]
            
            pattern = arguments.get("file_pattern", "*.fastq*")
            files = list(input_dir.glob(pattern))
            
            if not files:
                return [ErrorContent(text=f"No files found matching pattern '{pattern}' in {input_dir}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_dir = Path(tmpdir) / "fastqc_batch_output"
                output_dir.mkdir()
                
                # Build FastQC command for batch processing
                cmd = [
                    self.settings.fastqc_path,
                    "--outdir", str(output_dir),
                    "--threads", str(arguments.get("threads", 4)),
                    "--extract"
                ] + [str(f) for f in files]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return [ErrorContent(text=f"FastQC batch processing timed out after {self.settings.timeout} seconds")]
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"FastQC batch processing failed: {stderr.decode()}")]
                
                # Summarize batch results
                summary = await self._summarize_batch_results(output_dir, files)
                return [TextContent(text=summary)]
                
        except Exception as e:
            logger.error(f"Error running FastQC batch: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_multiqc(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            input_dir = Path(arguments["input_dir"])
            if not input_dir.exists():
                return [ErrorContent(text=f"Input directory not found: {input_dir}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_dir = Path(tmpdir) / "multiqc_output"
                output_dir.mkdir()
                
                cmd = [
                    self.settings.multiqc_path,
                    str(input_dir),
                    "--outdir", str(output_dir),
                    "--template", arguments.get("template", "default")
                ]
                
                if arguments.get("title"):
                    cmd.extend(["--title", arguments["title"]])
                if arguments.get("comment"):
                    cmd.extend(["--comment", arguments["comment"]])
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return [ErrorContent(text=f"MultiQC timed out after {self.settings.timeout} seconds")]
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"MultiQC failed: {stderr.decode()}")]
                
                # Get MultiQC report location
                report_html = output_dir / "multiqc_report.html"
                data_dir = output_dir / "multiqc_data"
                
                result = f"MultiQC report generated successfully!\n\n"
                result += f"Report: {report_html}\n"
                result += f"Data directory: {data_dir}\n\n"
                
                if report_html.exists():
                    result += f"Report size: {report_html.stat().st_size:,} bytes\n"
                
                if (data_dir / "multiqc_general_stats.txt").exists():
                    with open(data_dir / "multiqc_general_stats.txt") as f:
                        stats = f.read()
                        result += f"\nGeneral Statistics:\n{stats[:1000]}..."
                
                return [TextContent(text=result)]
                
        except Exception as e:
            logger.error(f"Error running MultiQC: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _parse_fastqc_results(self, output_dir: Path, filename_base: str) -> str:
        """Parse FastQC results and return summary"""
        try:
            # Look for extracted FastQC directory
            fastqc_dir = None
            for item in output_dir.iterdir():
                if item.is_dir() and filename_base in item.name:
                    fastqc_dir = item
                    break
            
            if not fastqc_dir:
                return "FastQC completed but results directory not found"
            
            # Parse fastqc_data.txt for key metrics
            data_file = fastqc_dir / "fastqc_data.txt"
            summary_file = fastqc_dir / "summary.txt"
            
            result = f"FastQC Analysis Complete for {filename_base}\n"
            result += "=" * 50 + "\n\n"
            
            # Parse summary (pass/warn/fail status)
            if summary_file.exists():
                with open(summary_file) as f:
                    summary_lines = f.readlines()
                    result += "Module Status Summary:\n"
                    for line in summary_lines:
                        parts = line.strip().split('\t')
                        if len(parts) >= 2:
                            status = parts[0]
                            module = parts[1]
                            emoji = "✅" if status == "PASS" else "⚠️" if status == "WARN" else "❌"
                            result += f"  {emoji} {module}: {status}\n"
                    result += "\n"
            
            # Parse basic statistics
            if data_file.exists():
                with open(data_file) as f:
                    content = f.read()
                    
                # Extract key metrics
                lines = content.split('\n')
                in_basic_stats = False
                result += "Basic Statistics:\n"
                
                for line in lines:
                    if line.startswith('>>Basic Statistics'):
                        in_basic_stats = True
                        continue
                    elif line.startswith('>>END_MODULE'):
                        in_basic_stats = False
                        continue
                    elif in_basic_stats and '\t' in line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            result += f"  • {parts[0]}: {parts[1]}\n"
            
            # Add file locations
            result += "\nOutput Files:\n"
            result += f"  • HTML Report: {fastqc_dir / 'fastqc_report.html'}\n"
            result += f"  • Data File: {data_file}\n"
            result += f"  • Summary: {summary_file}\n"
            
            return result
            
        except Exception as e:
            return f"Error parsing FastQC results: {str(e)}"
    
    async def _summarize_batch_results(self, output_dir: Path, files: list) -> str:
        """Summarize batch FastQC results"""
        try:
            result = f"FastQC Batch Analysis Complete\n"
            result += "=" * 40 + "\n\n"
            result += f"Processed {len(files)} files:\n\n"
            
            total_pass = total_warn = total_fail = 0
            
            for input_file in files:
                # Find corresponding FastQC directory
                base_name = input_file.stem.replace('.fastq', '').replace('.fq', '')
                fastqc_dir = None
                
                for item in output_dir.iterdir():
                    if item.is_dir() and base_name in item.name:
                        fastqc_dir = item
                        break
                
                if fastqc_dir and (fastqc_dir / "summary.txt").exists():
                    with open(fastqc_dir / "summary.txt") as f:
                        summary_lines = f.readlines()
                        
                    pass_count = sum(1 for line in summary_lines if line.startswith('PASS'))
                    warn_count = sum(1 for line in summary_lines if line.startswith('WARN'))
                    fail_count = sum(1 for line in summary_lines if line.startswith('FAIL'))
                    
                    total_pass += pass_count
                    total_warn += warn_count
                    total_fail += fail_count
                    
                    status = "✅" if fail_count == 0 and warn_count == 0 else "⚠️" if fail_count == 0 else "❌"
                    result += f"  {status} {input_file.name}: {pass_count}P/{warn_count}W/{fail_count}F\n"
                else:
                    result += f"  ❓ {input_file.name}: No results found\n"
            
            result += f"\nOverall Summary:\n"
            result += f"  • Total PASS: {total_pass}\n"
            result += f"  • Total WARN: {total_warn}\n"
            result += f"  • Total FAIL: {total_fail}\n\n"
            result += f"Output directory: {output_dir}\n"
            result += f"\nTip: Run multiqc_report on this directory to generate a combined report!\n"
            
            return result
            
        except Exception as e:
            return f"Error summarizing batch results: {str(e)}"
    
    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream)


async def main():
    logging.basicConfig(level=logging.INFO)
    server = FastQCServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())