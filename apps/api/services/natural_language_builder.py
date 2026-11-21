from typing import Dict, Any, Optional
import json
import logging
from fastapi import HTTPException
from apps.api.services.ollama_gateway import ollama_gateway

logger = logging.getLogger(__name__)

class NaturalLanguageBuilder:
    """
    Translates unstructured founder intent into validated schemas:
    1. Plain text -> React Flow Workflow DAG
    2. Plain text -> Custom Agent Configuration
    3. 'Teach a Process' -> Step-by-step verified automation
    """

    async def generate_workflow_from_prompt(self, user_prompt: str) -> Dict[str, Any]:
        system_prompt = (
            "You are the OneBoard Workflow Generation Engine. Convert the founder's automation request into a JSON structure.\n"
            "Required keys: 'name', 'description', 'trigger_type' (manual, schedule, webhook), 'trigger_config', "
            "'nodes' (array of {id, type, position: {x, y}, data: {label, connector, risk}}), "
            "'edges' (array of {id, source, target})."
        )
        
        res = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system_prompt,
            format_json=True
        )
        
        if res.get("simulated"):
            raise HTTPException(status_code=503, detail="Workflow generation requires a working AI model; no workflow was created.")
        try:
            parsed = json.loads(res["content"])
            nodes, edges = parsed["nodes"], parsed["edges"]
            if not isinstance(parsed.get("name"), str) or not parsed["name"].strip():
                raise ValueError("Missing workflow name")
            if not isinstance(nodes, list) or not isinstance(edges, list):
                raise ValueError("Workflow nodes and edges must be arrays")
            from apps.api.services.workflow_engine import workflow_engine
            validation = workflow_engine.validate_workflow({"nodes": nodes, "edges": edges})
            if not validation.get("is_valid"):
                raise ValueError(validation.get("error") or "Invalid workflow graph")
            parsed["simulated"] = False
            return parsed
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("AI returned an invalid workflow schema: %s", type(exc).__name__)
            raise HTTPException(status_code=422, detail="AI returned an invalid workflow. Please revise the prompt and retry.") from exc

    async def generate_agent_from_prompt(self, user_prompt: str) -> Dict[str, Any]:
        system_prompt = (
            "You are the OneBoard Agent Studio Generator. Convert a natural language agent description into a valid JSON schema.\n"
            "Required keys: 'name', 'role_title', 'department', 'description', 'system_prompt', "
            "'allowed_tools' (list of tool names), 'requires_approval_for' (list of sensitive tools), 'max_steps' (integer)."
        )
        
        res = await ollama_gateway.chat_complete(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system_prompt,
            format_json=True
        )
        
        if res.get("simulated"):
            raise HTTPException(status_code=503, detail="Agent generation requires a working AI model; no agent was created.")
        try:
            parsed = json.loads(res["content"])
            required = ("name", "role_title", "system_prompt")
            if not isinstance(parsed, dict) or any(
                not isinstance(parsed.get(key), str) or not parsed[key].strip() for key in required
            ):
                raise ValueError("Missing required agent fields")
            for key in ("allowed_tools", "requires_approval_for"):
                if not isinstance(parsed.get(key), list) or not all(isinstance(v, str) for v in parsed[key]):
                    raise ValueError("Invalid agent tool list")
            steps = parsed.get("max_steps")
            if type(steps) is not int or not 1 <= steps <= 25:
                raise ValueError("Invalid agent step limit")
            parsed["simulated"] = False
            return parsed
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("AI returned an invalid agent schema: %s", type(exc).__name__)
            raise HTTPException(status_code=422, detail="AI returned an invalid agent configuration. Please revise the prompt and retry.") from exc

    async def teach_a_process(self, process_description: str, example_inputs_outputs: Optional[str] = None) -> Dict[str, Any]:
        """
        'Teach a Process': Deconstructs repetitive founder tasks, identifies automation candidates,
        and produces a validated React Flow workflow with dry-run verification.
        """
        prompt = (
            f"The founder wants to teach OneBoard a repetitive process:\n"
            f"Description: {process_description}\n"
            f"Examples: {example_inputs_outputs or 'Standard business operations'}\n"
            f"Generate a step-by-step workflow DAG with trigger, data ingestion, processing, approval, and output action."
        )
        wf = await self.generate_workflow_from_prompt(prompt)
        wf["is_taught_process"] = True
        wf["original_description"] = process_description
        return wf

natural_language_builder = NaturalLanguageBuilder()
