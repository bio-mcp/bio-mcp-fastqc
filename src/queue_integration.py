"""
Queue integration mixin for MCP servers
This can be added to any bioinformatics MCP server to enable async job submission
"""
import httpx
import uuid
from typing import Optional, Dict, Any
from mcp.types import Tool, TextContent, ErrorContent
import logging

logger = logging.getLogger(__name__)


class QueueIntegrationMixin:
    """
    Mixin to add queue integration to any MCP server
    
    Usage:
        class MyToolServer(QueueIntegrationMixin, BaseServer):
            def __init__(self, queue_url="http://localhost:8000"):
                self.queue_url = queue_url
                super().__init__()
    """
    
    queue_url: str = "http://localhost:8000"
    
    def get_async_tools(self, tool_configs: Dict[str, Dict[str, Any]]) -> list[Tool]:
        """
        Generate async tool variants from configuration
        
        Args:
            tool_configs: Dict mapping tool names to their async config
                {
                    "blast": {
                        "job_type": "blastn",
                        "description": "Submit BLAST job to queue"
                    }
                }
        """
        async_tools = []
        
        # Add async variant for each tool
        for tool_name, config in tool_configs.items():
            async_tools.append(Tool(
                name=f"{tool_name}_async",
                description=f"{config['description']} (background job)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        **config.get("parameters", {}),
                        "priority": {
                            "type": "integer",
                            "description": "Job priority (1-10, default 5)",
                            "default": 5
                        },
                        "notification_email": {
                            "type": "string",
                            "description": "Email for completion notification"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for job organization"
                        }
                    },
                    "required": config.get("required_params", [])
                }
            ))
        
        # Add job management tools
        async_tools.extend([
            Tool(
                name="get_job_status",
                description="Check status of a background job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Job ID to check"
                        }
                    },
                    "required": ["job_id"]
                }
            ),
            Tool(
                name="get_job_result", 
                description="Retrieve results of completed job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Job ID to get results for"
                        }
                    },
                    "required": ["job_id"]
                }
            ),
            Tool(
                name="list_my_jobs",
                description="List recent jobs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["pending", "running", "completed", "failed", "all"],
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10
                        }
                    }
                }
            ),
            Tool(
                name="cancel_job",
                description="Cancel a running job",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Job ID to cancel"
                        }
                    },
                    "required": ["job_id"]
                }
            )
        ])
        
        return async_tools
    
    async def submit_job(
        self,
        job_type: str,
        parameters: Dict[str, Any],
        priority: int = 5,
        tags: Optional[list] = None
    ) -> Dict[str, Any]:
        """Submit job to queue system"""
        try:
            # First, upload any local files to queue storage
            processed_params = await self._prepare_job_parameters(parameters)
            
            job_request = {
                "job_type": job_type,
                "parameters": processed_params,
                "priority": priority,
                "tags": tags or []
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.queue_url}/jobs/submit",
                    json=job_request,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    raise Exception(f"Failed to submit job: {response.text}")
                
                return response.json()
                
        except Exception as e:
            logger.error(f"Error submitting job: {e}")
            raise
    
    async def _prepare_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare parameters for job submission
        Upload local files and convert paths to URLs
        """
        processed = parameters.copy()
        
        # Check for file parameters that need uploading
        for key, value in parameters.items():
            if isinstance(value, str) and value.startswith("/") and "file" in key.lower():
                # This is likely a local file path
                # In production, would upload to MinIO and get URL
                # For now, just pass through
                logger.info(f"Would upload file: {value}")
        
        return processed
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get job status from queue"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.queue_url}/jobs/{job_id}/status",
                timeout=10.0
            )
            
            if response.status_code == 404:
                raise Exception(f"Job {job_id} not found")
            elif response.status_code != 200:
                raise Exception(f"Failed to get job status: {response.text}")
            
            return response.json()
    
    async def get_job_result(self, job_id: str) -> Dict[str, Any]:
        """Get job results from queue"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.queue_url}/jobs/{job_id}/result",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to get results: {response.text}")
            
            return response.json()
    
    async def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a running job"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.queue_url}/jobs/{job_id}",
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to cancel job: {response.text}")
            
            return response.json()
    
    # Helper method to format job status for display
    def format_job_status(self, job_info: Dict[str, Any]) -> str:
        """Format job status for user display"""
        status = f"Job ID: {job_info['job_id']}\n"
        status += f"Type: {job_info['job_type']}\n"
        status += f"Status: {job_info['status']}\n"
        status += f"Created: {job_info['created_at']}\n"
        
        if job_info.get('started_at'):
            status += f"Started: {job_info['started_at']}\n"
        
        if job_info.get('progress'):
            status += f"Progress: {job_info['progress']}%\n"
        
        if job_info['status'] == 'completed':
            status += f"Completed: {job_info['completed_at']}\n"
            if job_info.get('result_url'):
                status += f"\nResults available at: {job_info['result_url']}"
        elif job_info['status'] == 'failed':
            status += f"Error: {job_info.get('error', 'Unknown error')}\n"
        
        return status