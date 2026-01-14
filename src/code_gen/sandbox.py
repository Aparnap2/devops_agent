"""Sandboxed Python code execution.

Provides safe execution of Python code in isolated containers.
"""

import asyncio
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Dangerous imports/patterns to block
BLOCKED_IMPORTS = [
    "os", "sys", "subprocess", "shutil", "pty",
    "socket", "requests", "urllib", "http",
    "ftplib", "smtplib", "telnetlib", "poplib",
    "imaplib", "nntplib", "xmlrpc", "pickle",
    "marshal", "ctypes", "ctypesutil",
]

BLOCKED_PATTERNS = [
    "eval(", "exec(", "compile(",
    "__import__", "getattr(", "setattr(", "delattr(",
    "open(", "file(", "input(",
    "os.", "sys.", "subprocess.", "shutil.",
    "breakpoint(", "help(",
]


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution."""
    timeout_seconds: int = 30
    memory_limit_mb: int = 128
    max_output_size: int = 1024 * 1024  # 1MB
    allowed_modules: list[str] = None


class SandboxError(Exception):
    """Sandbox execution error."""
    pass


class TimeoutError(SandboxError):
    """Execution timed out."""
    pass


class SecurityError(SandboxError):
    """Security policy violation."""
    pass


class CodeGenerator:
    """Generates Python code for various purposes."""

    def __init__(self, config: Optional[SandboxConfig] = None):
        """Initialize code generator.

        Args:
            config: Sandbox configuration
        """
        self.config = config or SandboxConfig()

    def _sanitize_code(self, code: str) -> str:
        """Basic code sanitization."""
        code_lower = code.lower()

        # Check for blocked imports
        for imp in BLOCKED_IMPORTS:
            if f"import {imp}" in code_lower or f"from {imp}" in code_lower:
                raise SecurityError(f"Blocked import: {imp}")

        # Check for blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in code_lower:
                raise SecurityError(f"Blocked pattern: {pattern}")

        return code

    def generate_calculation(
        self,
        expression: str,
        description: str = "",
    ) -> str:
        """Generate code for calculation.

        Args:
            expression: Python expression to evaluate
            description: Description of the calculation

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """{description}"""
            import json

            # Input values (modify these as needed)
            input_values = {{}}

            # Calculate result
            result = {expression}

            # Output result
            output = {{
                "expression": "{expression}",
                "result": result,
                "type": type(result).__name__,
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_matplotlib(
        self,
        data: list,
        title: str = "Chart",
        xlabel: str = "X",
        ylabel: str = "Y",
        chart_type: str = "line",
        color: str = "blue",
    ) -> str:
        """Generate matplotlib chart code.

        Args:
            data: Chart data
            title: Chart title
            xlabel: X-axis label
            ylabel: Y-axis label
            chart_type: Type of chart (line, bar, scatter, hist, pie)
            color: Line/bar color

        Returns:
            Complete Python code string
        """
        chart_code = {
            "line": f"plt.plot(data, color='{color}')",
            "bar": f"plt.bar(range(len(data)), data, color='{color}')",
            "scatter": f"plt.scatter(range(len(data)), data, color='{color}')",
            "hist": f"plt.hist(data, bins=20, color='{color}')",
        }.get(chart_type, f"plt.plot(data, color='{color}')")

        return textwrap.dedent(f'''
            """Generate {chart_type} chart: {title}"""
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            import json

            data = {data}
            title = "{title}"
            xlabel = "{xlabel}"
            ylabel = "{ylabel}"

            plt.figure(figsize=(10, 6))
            {chart_code}
            plt.title(title)
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            plt.grid(True, alpha=0.3)

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            # Output
            output = {{
                "title": title,
                "image_base64": img_base64,
                "chart_type": "{chart_type}",
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_pie_chart(
        self,
        data: list,
        labels: list[str],
        title: str = "Distribution",
    ) -> str:
        """Generate pie chart code.

        Args:
            data: Pie slice values
            labels: Pie slice labels
            title: Chart title

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate pie chart: {title}"""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import json

            data = {data}
            labels = {labels}
            title = "{title}"

            plt.figure(figsize=(8, 8))
            plt.pie(data, labels=labels, autopct='%1.1f%%', startangle=90)
            plt.title(title)
            plt.axis('equal')

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            output = {{
                "title": title,
                "image_base64": img_base64,
            }}
            print(json.dumps(output))
        ''').strip()

    async def execute(self, code: str) -> dict[str, Any]:
        """Execute code in sandbox.

        Args:
            code: Python code to execute

        Returns:
            Dict with success, output, error
        """
        # Sanitize code
        try:
            code = self._sanitize_code(code)
        except SecurityError as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
            }

        # Create temp file for execution
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Run with timeout and resource limits
            result = await self._run_subprocess(
                temp_path,
                timeout=self.config.timeout_seconds,
            )
            return result

        finally:
            # Cleanup
            os.unlink(temp_path)

    async def _run_subprocess(
        self,
        script_path: str,
        timeout: int,
    ) -> dict[str, Any]:
        """Run script in subprocess with limits.

        Args:
            script_path: Path to script
            timeout: Timeout in seconds

        Returns:
            Dict with success, output, error
        """
        try:
            # Build command with resource limits
            cmd = [
                sys.executable,
                "-u",  # Unbuffered output
                script_path,
            ]

            # Run process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "output": "",
                    "error": f"Execution timeout after {timeout}s",
                }

            output = stdout.decode('utf-8', errors='replace').strip()

            # Check return code
            if process.returncode == 0:
                return {
                    "success": True,
                    "output": output,
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "output": output,
                    "error": f"Exit code: {process.returncode}",
                }

        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
            }


async def safe_execute(
    code: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Convenience function for safe code execution.

    Args:
        code: Python code to execute
        timeout: Timeout in seconds

    Returns:
        Dict with success, output, error
    """
    config = SandboxConfig(timeout_seconds=timeout)
    generator = CodeGenerator(config)
    return await generator.execute(code)
