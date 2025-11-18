"""
AI-powered schema generation using LLMs.
"""
import json
import logging
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)


class AISchemaGenerator:
    """
    Generate scraping schemas using AI/LLM.
    """

    def __init__(self, model: Optional[str] = None):
        """
        Initialize AI schema generator.

        Args:
            model: AI model to use (default from settings)
        """
        self.model = model or settings.DEFAULT_AI_MODEL
        self.openai_key = settings.OPENAI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY

    def _get_ai_client(self):
        """Get appropriate AI client based on model."""
        if self.model.startswith('gpt'):
            if not self.openai_key:
                raise ValueError("OpenAI API key not configured")
            import openai
            return openai.OpenAI(api_key=self.openai_key)
        elif self.model.startswith('claude'):
            if not self.anthropic_key:
                raise ValueError("Anthropic API key not configured")
            import anthropic
            return anthropic.Anthropic(api_key=self.anthropic_key)
        else:
            raise ValueError(f"Unsupported model: {self.model}")

    def _simplify_html(self, html: str, max_length: int = 15000) -> str:
        """
        Simplify HTML by removing scripts, styles, and limiting length.

        Args:
            html: Full HTML content
            max_length: Maximum length of simplified HTML

        Returns:
            Simplified HTML string
        """
        soup = BeautifulSoup(html, 'lxml')

        # Remove script and style elements
        for element in soup(['script', 'style', 'noscript', 'iframe']):
            element.decompose()

        # Get text with some structure
        html_text = soup.prettify()

        # Truncate if too long
        if len(html_text) > max_length:
            html_text = html_text[:max_length] + "\n... (truncated)"

        return html_text

    def _create_schema_prompt(
        self,
        html_samples: List[str],
        user_prompt: str
    ) -> str:
        """
        Create prompt for AI schema generation.

        Args:
            html_samples: List of HTML samples
            user_prompt: User's scraping request

        Returns:
            Formatted prompt string
        """
        prompt = f"""You are an AI extraction engine specialized in web scraping. Your task is to analyze HTML content and create a structured data extraction schema.

USER REQUEST:
{user_prompt}

HTML SAMPLES:
"""
        for i, html in enumerate(html_samples, 1):
            simplified = self._simplify_html(html)
            prompt += f"\n--- Sample {i} ---\n{simplified}\n"

        prompt += """

TASK:
1. Analyze the HTML structure and content
2. Identify repeating patterns (list items, table rows, cards, etc.)
3. Create a JSON schema that satisfies the user's request
4. Provide CSS selectors for each field
5. Generate 5-10 sample data items

OUTPUT FORMAT (respond with valid JSON only):
{
  "schema": {
    "container": "CSS selector for repeating items (or null for single item)",
    "fields": {
      "field_name": {
        "selector": "CSS selector",
        "attr": "text|href|src|data-*|html",
        "type": "string|number|url|date",
        "description": "What this field contains"
      }
    }
  },
  "pagination": {
    "type": "selector|url_pattern|none",
    "next_selector": "CSS selector for next page link (if type=selector)",
    "pattern": "URL pattern with {page} placeholder (if type=url_pattern)"
  },
  "sample_items": [
    {
      "field_name": "value",
      ...
    }
  ],
  "confidence": 0.0-1.0,
  "notes": "Any important notes about the extraction"
}

IMPORTANT:
- Use specific CSS selectors that will reliably extract the data
- Prefer class-based selectors over tag-only selectors
- Test your selectors mentally against the HTML structure
- Ensure the schema is reusable for similar pages
- Include all fields requested by the user
- Set confidence based on HTML structure clarity
"""
        return prompt

    async def generate_schema(
        self,
        html_samples: List[str],
        user_prompt: str
    ) -> Dict[str, Any]:
        """
        Generate extraction schema using AI.

        Args:
            html_samples: List of HTML content samples
            user_prompt: User's natural language request

        Returns:
            Dictionary containing schema, selectors, and sample items
        """
        try:
            prompt = self._create_schema_prompt(html_samples, user_prompt)

            if self.model.startswith('gpt'):
                result = await self._generate_with_openai(prompt)
            elif self.model.startswith('claude'):
                result = await self._generate_with_anthropic(prompt)
            else:
                raise ValueError(f"Unsupported model: {self.model}")

            # Parse JSON response
            schema_data = self._parse_ai_response(result)

            return {
                'success': True,
                'schema': schema_data.get('schema', {}),
                'pagination': schema_data.get('pagination', {}),
                'sample_items': schema_data.get('sample_items', []),
                'confidence': schema_data.get('confidence', 0.8),
                'notes': schema_data.get('notes', ''),
                'model_used': self.model
            }

        except Exception as e:
            logger.error(f"AI schema generation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'schema': {},
                'sample_items': []
            }

    async def _generate_with_openai(self, prompt: str) -> str:
        """
        Generate schema using OpenAI.

        Args:
            prompt: Formatted prompt

        Returns:
            AI response text
        """
        import openai

        client = openai.OpenAI(api_key=self.openai_key)

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a web scraping expert. Always respond with valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=settings.AI_TEMPERATURE,
            max_tokens=settings.AI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )

        return response.choices[0].message.content

    async def _generate_with_anthropic(self, prompt: str) -> str:
        """
        Generate schema using Anthropic Claude.

        Args:
            prompt: Formatted prompt

        Returns:
            AI response text
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self.anthropic_key)

        message = client.messages.create(
            model=self.model,
            max_tokens=settings.AI_MAX_TOKENS,
            temperature=settings.AI_TEMPERATURE,
            system="You are a web scraping expert. Always respond with valid JSON.",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return message.content[0].text

    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """
        Parse AI response to extract JSON.

        Args:
            response: AI response text

        Returns:
            Parsed JSON dictionary
        """
        # Try to find JSON in the response
        import re

        # Remove markdown code blocks if present
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*', '', response)

        # Parse JSON
        try:
            data = json.loads(response)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.debug(f"Response content: {response}")
            raise ValueError("AI returned invalid JSON")

    async def refine_schema(
        self,
        schema: Dict[str, Any],
        html_sample: str,
        feedback: str
    ) -> Dict[str, Any]:
        """
        Refine existing schema based on feedback.

        Args:
            schema: Current schema
            html_sample: HTML sample
            feedback: User feedback

        Returns:
            Refined schema
        """
        prompt = f"""You are refining a web scraping schema based on user feedback.

CURRENT SCHEMA:
{json.dumps(schema, indent=2)}

HTML SAMPLE:
{self._simplify_html(html_sample)}

USER FEEDBACK:
{feedback}

TASK:
Modify the schema to address the user's feedback. Return the updated schema in the same JSON format.
"""

        try:
            if self.model.startswith('gpt'):
                result = await self._generate_with_openai(prompt)
            else:
                result = await self._generate_with_anthropic(prompt)

            refined_data = self._parse_ai_response(result)

            return {
                'success': True,
                'schema': refined_data.get('schema', schema),
                'notes': refined_data.get('notes', '')
            }

        except Exception as e:
            logger.error(f"Schema refinement failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'schema': schema
            }


class SchemaValidator:
    """
    Validate extraction schemas.
    """

    @staticmethod
    def validate_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a scraping schema.

        Args:
            schema: Schema to validate

        Returns:
            Validation result
        """
        errors = []
        warnings = []

        # Check required fields
        if 'fields' not in schema:
            errors.append("Schema must have 'fields' key")
            return {'valid': False, 'errors': errors, 'warnings': warnings}

        fields = schema['fields']
        if not isinstance(fields, dict):
            errors.append("'fields' must be a dictionary")
            return {'valid': False, 'errors': errors, 'warnings': warnings}

        if len(fields) == 0:
            errors.append("Schema must have at least one field")
            return {'valid': False, 'errors': errors, 'warnings': warnings}

        # Validate each field
        for field_name, field_config in fields.items():
            if not isinstance(field_config, dict):
                errors.append(f"Field '{field_name}' config must be a dictionary")
                continue

            if 'selector' not in field_config:
                errors.append(f"Field '{field_name}' missing 'selector'")

            if 'type' not in field_config:
                warnings.append(f"Field '{field_name}' missing 'type', defaulting to 'string'")

        # Check pagination
        if 'pagination' in schema:
            pagination = schema['pagination']
            if pagination.get('type') == 'selector' and not pagination.get('next_selector'):
                warnings.append("Pagination type is 'selector' but 'next_selector' is missing")
            elif pagination.get('type') == 'url_pattern' and not pagination.get('pattern'):
                warnings.append("Pagination type is 'url_pattern' but 'pattern' is missing")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
