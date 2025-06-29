"""
FastQC MCP server with queue support for long-running jobs
"""
from typing import Any, Optional
from mcp.types import TextContent, ErrorContent
from .server import FastQCServer
from .queue_integration import QueueIntegrationMixin


class FastQCServerWithQueue(QueueIntegrationMixin, FastQCServer):
    """FastQC server with async job queue support"""
    
    def __init__(self, settings=None, queue_url: Optional[str] = None):
        # Set queue URL before calling parent init
        self.queue_url = queue_url or "http://localhost:8000"
        super().__init__(settings)
        self._setup_async_handlers()
    
    def _setup_async_handlers(self):
        """Add async handlers to existing tools"""
        
        # Define which tools should have async variants
        async_tool_configs = {
            "fastqc_single": {
                "job_type": "fastqc_single",
                "description": "Run FastQC quality control on a single FASTQ/FASTA file (async)",
                "parameters": {
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
                "required_params": ["input_file"]
            },
            "fastqc_batch": {
                "job_type": "fastqc_batch", 
                "description": "Run FastQC on multiple files in a directory (async)",
                "parameters": {
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
                "required_params": ["input_dir"]
            },
            "multiqc_report": {
                "job_type": "multiqc_report",
                "description": "Generate MultiQC report from directory of analysis results (async)",
                "parameters": {
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
                "required_params": ["input_dir"]
            }
        }
        
        @self.server.list_tools()
        async def list_tools():
            # Get base tools from parent
            base_tools = await super(FastQCServerWithQueue, self).server.list_tools()
            
            # Add async variants
            async_tools = self.get_async_tools(async_tool_configs)
            
            return base_tools + async_tools
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any):
            # Handle async tools
            if name.endswith("_async"):
                base_name = name[:-6]  # Remove _async suffix
                if base_name in async_tool_configs:
                    return await self._handle_async_tool(
                        base_name,
                        async_tool_configs[base_name]["job_type"],
                        arguments
                    )
            
            # Handle job management tools
            elif name == "get_job_status":
                return await self._handle_job_status(arguments["job_id"])
            elif name == "get_job_result":
                return await self._handle_job_result(arguments["job_id"])
            elif name == "list_my_jobs":
                return await self._handle_list_jobs(arguments)
            elif name == "cancel_job":
                return await self._handle_cancel_job(arguments["job_id"])
            
            # Otherwise delegate to parent
            else:
                return await super(FastQCServerWithQueue, self).server.call_tool(name, arguments)
    
    async def _handle_async_tool(
        self,
        tool_name: str,
        job_type: str,
        arguments: dict
    ) -> list[TextContent | ErrorContent]:
        """Submit tool job to queue"""
        try:
            # Extract queue-specific parameters
            priority = arguments.pop("priority", 5)
            tags = arguments.pop("tags", [])
            notification_email = arguments.pop("notification_email", None)
            
            # Submit job
            job_info = await self.submit_job(
                job_type=job_type,
                parameters=arguments,
                priority=priority,
                tags=tags
            )
            
            return [TextContent(
                text=f"FastQC job submitted successfully!\n\n"
                     f"{self.format_job_status(job_info)}\n\n"
                     f"Use 'get_job_status' with job ID to check progress.\n"
                     f"Large batch jobs may take 10-30 minutes depending on file size."
            )]
            
        except Exception as e:
            return [ErrorContent(text=f"Error submitting FastQC job: {str(e)}")]
    
    async def _handle_job_status(self, job_id: str) -> list[TextContent | ErrorContent]:
        """Get job status"""
        try:
            job_info = await self.get_job_status(job_id)
            return [TextContent(text=self.format_job_status(job_info))]
        except Exception as e:
            return [ErrorContent(text=str(e))]
    
    async def _handle_job_result(self, job_id: str) -> list[TextContent | ErrorContent]:
        """Get job results"""
        try:
            result = await self.get_job_result(job_id)
            
            result_text = f"FastQC Job {job_id} Results\n"
            result_text += "=" * 50 + "\n\n"
            
            if "summary" in result:
                result_text += "Quality Control Summary:\n"
                for key, value in result["summary"].items():
                    result_text += f"  • {key}: {value}\n"
                result_text += "\n"
            
            if "files_processed" in result:
                result_text += f"Files processed: {result['files_processed']}\n"
            
            if "warnings" in result:
                result_text += f"Quality warnings: {result['warnings']}\n"
                
            if "failures" in result:
                result_text += f"Quality failures: {result['failures']}\n"
            
            if "result_url" in result:
                result_text += f"\nFull results: {result['result_url']}\n"
                result_text += "HTML reports and MultiQC data available for download.\n"
                result_text += "Results available for 7 days.\n"
            
            return [TextContent(text=result_text)]
            
        except Exception as e:
            return [ErrorContent(text=str(e))]
    
    async def _handle_list_jobs(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """List user's jobs - would need to implement in API"""
        return [TextContent(
            text="Job listing not yet implemented.\n"
                 "Use individual job IDs to check status.\n"
                 "Example: get_job_status with your job ID"
        )]
    
    async def _handle_cancel_job(self, job_id: str) -> list[TextContent | ErrorContent]:
        """Cancel a job"""
        try:
            result = await self.cancel_job(job_id)
            return [TextContent(text=f"FastQC job {job_id} cancelled successfully")]
        except Exception as e:
            return [ErrorContent(text=str(e))]