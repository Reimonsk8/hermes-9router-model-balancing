import sqlite3
import yaml
import os

def load_config():
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def get_model_chain(config):
    """
    Returns the ordered list of models: first the default,
    then all fallback providers.
    """
    chain = []
    
    # 1. Default model
    default_model = config.get("model", {}).get("default")
    if default_model:
        chain.append(default_model)
        
    # 2. Fallback providers
    for provider in config.get("fallback_providers", []):
        model = provider.get("model")
        if model and model not in chain:
            chain.append(model)
            
    return chain

def get_usage_metrics():
    db_path = os.path.expanduser("~/.hermes/state.db")
    metrics = {}
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Querying model usage
        cursor.execute("SELECT model, SUM(input_tokens + output_tokens + reasoning_tokens) FROM sessions GROUP BY model")
        for row in cursor.fetchall():
            if row[0]:
                metrics[row[0]] = row[1]
        conn.close()
    return metrics

def progress_bar(tokens, max_tokens, bar_length=20):
    # If max_tokens is 0, we treat it as 0% usage
    if max_tokens <= 0:
        return f"[{'░' * bar_length}] 0%"
    
    percent = (tokens / max_tokens) * 100
    filled = int(bar_length * tokens // max_tokens)
    bar = "█" * filled + "░" * (bar_length - filled)
    return f"[{bar}] {int(percent)}%"

def main():
    config = load_config()
    model_chain = get_model_chain(config)
    metrics = get_usage_metrics()
    
    # Define what "full capacity" looks like. 
    # For now, we take the max token usage found to represent 100% capacity.
    all_metrics = list(metrics.values())
    max_tokens_found = max(all_metrics) if all_metrics else 0
    
    print(f"{'Model Name':<50} | {'Tokens':<12} | {'Usage Status'}")
    print("-" * 85)
    
    # Sort models by token usage (ascending), then the rest
    sorted_models = sorted(model_chain, key=lambda m: metrics.get(m, 0))
    
    # We display every model in the configuration chain, sorted by usage.
    for model in sorted_models:
        tokens = metrics.get(model, 0)
        
        # Display model metrics
        # Use max_tokens_found as the baseline for "full"
        bar = progress_bar(tokens, max_tokens_found)
        print(f"{model:<50} | {tokens:<12,d} | {bar}")
        
    print("-" * 85)
    print(f"Total Tokens Tracked: {sum(all_metrics):,d}")

if __name__ == "__main__":
    main()
