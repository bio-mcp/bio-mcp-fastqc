#!/usr/bin/env python3
"""
Example of using the {{tool_name}} MCP server directly
"""

import asyncio
import json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    # Create server parameters
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.server"],
        env={"BIO_MCP_TIMEOUT": "60"}
    )
    
    # Connect to server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # Example: Run {{tool_name}}
            result = await session.call_tool(
                "{{tool_name}}_run",
                {
                    "input_file": "example_data/sample.{{input_extension}}",
                    # Add other parameters
                }
            )
            
            print("\nResult:")
            for content in result:
                if hasattr(content, 'text'):
                    print(content.text)
                elif hasattr(content, 'error'):
                    print(f"Error: {content.error}")


if __name__ == "__main__":
    asyncio.run(main())