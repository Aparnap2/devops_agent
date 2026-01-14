#!/usr/bin/env python3
"""Test script for Ollama integration using OpenAI SDK.

Tests local LLM connection and structured output generation.
"""

import asyncio
import json
import sys

from src.llm.ollama import OllamaClient, get_ollama_client


async def test_ollama_connection():
    """Test connection to Ollama."""
    print("=" * 60)
    print("🧪 Testing Ollama Connection")
    print("=" * 60)

    client = get_ollama_client()
    print(f"\n📡 Connecting to: {client.base_url}")
    print(f"🤖 Model: {client.model}")

    # Check availability
    print("\n🔍 Checking availability...")
    available = await client.is_available()

    if available:
        print("✅ Ollama is running and model is available!")
    else:
        print("⚠️  Ollama health check failed")
        return False

    return True


async def test_simple_generation():
    """Test simple text generation."""
    print("\n" + "=" * 60)
    print("📝 Testing Simple Generation")
    print("=" * 60)

    client = get_ollama_client()

    prompt = "Explain what an OOMKilled error means in Kubernetes in 2 sentences."
    print(f"\n💬 Prompt: '{prompt}'")

    response = await client.generate(
        prompt=prompt,
        temperature=0.1,
    )

    print(f"\n🤖 Response:")
    print("-" * 40)
    print(response.content)
    print("-" * 40)

    return True


async def test_structured_output():
    """Test structured JSON output generation."""
    print("\n" + "=" * 60)
    print("📋 Testing Structured Output")
    print("=" * 60)

    # Define a schema for root cause analysis
    schema = {
        "type": "object",
        "properties": {
            "cause": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "suggested_actions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["cause", "confidence", "suggested_actions"],
    }

    prompt = """
Analyze this Kubernetes event:

Event: OOMKilled
Message: Container demo-app exceeded memory limit (512Mi)
Pod: demo-app-abc
Namespace: production

Provide the root cause analysis in JSON format.
"""

    print("\n💬 Prompt: Analyzing OOMKilled event...")
    print(f"📐 Schema: {json.dumps(schema, indent=2)}")

    client = get_ollama_client()
    try:
        result = await client.generate_structured(
            prompt=prompt,
            schema=schema,
            system="You are a Kubernetes SRE expert. Analyze incidents and provide root cause analysis.",
        )

        print(f"\n✅ Structured Output:")
        print(json.dumps(result, indent=2))

        # Validate
        assert "cause" in result
        assert "confidence" in result
        assert "suggested_actions" in result
        print("\n✅ Output matches schema!")

        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_hypothesis_generation():
    """Test generating multiple hypotheses."""
    print("\n" + "=" * 60)
    print("🧠 Testing Hypothesis Generation")
    print("=" * 60)

    schema = {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "cause": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "suggested_actions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "cause", "confidence", "suggested_actions"],
                },
            },
        },
        "required": ["hypotheses"],
    }

    prompt = """
Analyze this incident:

Observations:
- Event: CrashLoopBackOff (occurred 5 times in last hour)
- Pod: api-gateway-xyz is in CrashLoopBackOff state
- Container restart count: 10
- Last exit code: 137 (SIGKILL)

Generate hypotheses for the root cause in JSON format.
"""

    print("\n💬 Prompt: Analyzing CrashLoopBackOff incident...")

    client = get_ollama_client()
    try:
        result = await client.generate_structured(
            prompt=prompt,
            schema=schema,
            system="You are a Kubernetes SRE expert. Generate multiple root cause hypotheses.",
        )

        print(f"\n✅ Hypotheses Generated:")
        for i, hyp in enumerate(result.get("hypotheses", []), 1):
            print(f"\n{i}. {hyp['cause']}")
            print(f"   Confidence: {hyp.get('confidence', 0):.0%}")
            print(f"   Actions: {', '.join(hyp.get('suggested_actions', []))}")

        assert len(result.get("hypotheses", [])) >= 1
        print("\n✅ Hypothesis generation working!")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("🚀 SRE Agent - Ollama Integration Tests")
    print("=" * 60)

    results = []
    client = get_ollama_client()

    # Test 1: Connection
    try:
        results.append(("Connection", await test_ollama_connection()))
    except Exception as e:
        print(f"\n❌ Connection test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Connection", False))

    # Test 2: Simple generation
    if results[-1][1]:  # Only if connected
        try:
            results.append(("Simple Generation", await test_simple_generation()))
        except Exception as e:
            print(f"\n❌ Simple generation failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(("Simple Generation", False))

    # Test 3: Structured output
    if results[-1][1]:  # Only if connected
        try:
            results.append(("Structured Output", await test_structured_output()))
        except Exception as e:
            print(f"\n❌ Structured output failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(("Structured Output", False))

    # Test 4: Hypothesis generation
    if results[-1][1]:  # Only if connected
        try:
            results.append(("Hypothesis Generation", await test_hypothesis_generation()))
        except Exception as e:
            print(f"\n❌ Hypothesis generation failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(("Hypothesis Generation", False))

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    passed = 0
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status}: {name}")
        if result:
            passed += 1

    print(f"\n   Total: {passed}/{len(results)} tests passed")

    # Cleanup
    await client.close()

    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
