import os
import tempfile
from hermes_metrics import load_config, get_usage_metrics, load_model_limits, get_session_metrics, sanitize_prometheus_label

def update_metrics():
    config = load_config()
    current_session = get_session_metrics()
    limits = load_model_limits(config)
    
    if not current_session:
        return

    model = current_session["model"]
    used = current_session["used"]
    max_tokens = limits.get(model, 128000) # Fallback default
    remaining = max_tokens - used
    utilization = (used / max_tokens) * 100

    label_model = sanitize_prometheus_label(model)
    
    lines = [
        f'hermes_context_used_tokens{{model="{label_model}"}} {used}',
        f'hermes_context_max_tokens{{model="{label_model}"}} {max_tokens}',
        f'hermes_context_remaining_tokens{{model="{label_model}"}} {remaining}',
        f'hermes_context_utilization_percent{{model="{label_model}"}} {utilization:.2f}'
    ]
    
    output_path = "/root/.hermes/metrics/context.prom"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(output_path))
    try:
        with os.fdopen(fd, 'w') as f:
            f.write("\n".join(lines) + "\n")
        os.replace(temp_path, output_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e

if __name__ == "__main__":
    update_metrics()
