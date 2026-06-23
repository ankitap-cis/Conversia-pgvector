from langchain_core.callbacks import BaseCallbackHandler
from typing import Optional, Dict, List, Any
import logging
import tiktoken
import configparser

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read("config.ini")
embed_model = config['openAI_config']['embedding_model']

class TokenUsageCallback(BaseCallbackHandler):
    def __init__(self, debug: bool = False,):
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.successful = False
        self.last_model_name: Optional[str] = None
        self.debug = debug

    def reset(self):
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.successful = False
        self.last_model_name = None

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        if self.debug:
            logger.debug(f"LLM started with prompts: {prompts}")
    
    def on_llm_end(self, response, **kwargs) -> None:
        if self.debug:
            logger.debug(f"LLM ended with response: {response}")

        try:
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})

                if token_usage:
                    self.prompt_tokens = token_usage.get("prompt_tokens", 0)
                    self.completion_tokens = token_usage.get("completion_tokens", 0)
                    self.total_tokens = token_usage.get("total_tokens", 0)
                    self.successful = True

                    return
                
            if hasattr(response, "generations") and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "generation_info") and gen.generation_info:
                            if hasattr(gen.generation_info, "prompt_tokens") and gen.generation_info.prompt_tokens:
                                self.prompt_tokens = gen.generation_info.get("prompt_tokens", 0)
                                self.completion_tokens = gen.generation_info.get("completion_tokens", 0)
                                self.total_tokens = gen.generation_info.get("total_tokens", 0)
                                self.successful = True
                                return
                        
                        if hasattr(gen, "message"):
                            msg = gen.message

                            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                                usage = msg.usage_metadata

                                if hasattr(usage, "prompt_tokens") and usage.prompt_tokens:
                                    self.prompt_tokens = usage.get("prompt_tokens", 0)
                                    self.completion_tokens = usage.get("completion_tokens", 0)
                                    self.total_tokens = usage.get("total_tokens", 0)
                                    self.successful = True
                                    return
                                if "input_tokens" in usage.keys():
                                    self.prompt_tokens = usage.get("input_tokens", 0)
                                    self.completion_tokens = usage.get("output_tokens", 0)
                                    self.total_tokens = usage.get("total_tokens", 0)
                                    self.successful = True
                                    return
                                
                        
                            if hasattr(msg, "response_metadata") and msg.response_metadata:
                                usage = msg.response_metadata.get("token_usage", {})
                                if usage:
                                    self.prompt_tokens = usage.get("prompt_tokens", 0)
                                    self.completion_tokens = usage.get("completion_tokens", 0)
                                    self.total_tokens = usage.get("total_tokens", 0)
                                    self.successful = True
                                    return
        except Exception as e:
            logger.warning(f"Token extraction failed: {e}")

    def on_llm_error(self, error: Exception, **kwargs) -> None:
        if self.debug:
            logger.debug(f"LLM error occurred: {error}")

    def get_usage_dict(self) -> Dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "successful": self.successful,
            "model_name": self.last_model_name
        }
    
    def __str__(self) -> str:
        if self.successful:
            return (
                f"TokenUsage(prompt={self.prompt_tokens}, "
                f"completion={self.completion_tokens}, "
                f"total={self.total_tokens})"
            )
        return "TokenUsage(not captured)"
    

def embedding_token_count(texts: List, model: str = embed_model) -> dict:
    try:
        encoding = tiktoken.get_encoding("cl100k_base")

        total_tokens = 0
        for text in texts:
            total_tokens += len(encoding.encode(text))

        return {
            "total_tokens": total_tokens,
            "model": model,
        }
    except Exception as e:
        return {
            "total_tokens": 0,
            "model": model,
        }