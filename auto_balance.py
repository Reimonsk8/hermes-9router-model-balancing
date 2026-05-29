import yaml
import subprocess
import os

# Config path
CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")

def get_model_usage():
    # Run the existing monitor script/logic to get usage data
    # We'll parse it from the output or run the same logic
    # For now, running the script and capturing output
    result = subprocess.run(["python3", ".hermes/scripts/monitor_models.py"], capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')
    
    models = []
    # Skip header and separator lines
    for line in lines[2:-2]: 
        parts = line.split('|')
        if len(parts) >= 3:
            name = parts[0].strip()
            tokens = int(parts[1].replace(',', '').strip())
            # The output has a visual bar, then the percentage. 
            # Example: [██░░░░░░░░░░░░░░░░░░] 13%
            usage_str = parts[2].split(']')[-1].replace('%', '').strip()
            usage = int(usage_str)
            models.append({'name': name, 'usage': usage})
    
    return models

def update_fallback_order():
    models = get_model_usage()
    
    # Sort: Low usage to High usage
    sorted_models = sorted(models, key=lambda x: x['usage'])
    
    # Load config
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    
    # Update fallback models list
    # Assuming 'fallback_models' key exists in config
    new_fallback_order = [m['name'] for m in sorted_models]
    config['fallback_models'] = new_fallback_order
    
    # Write back
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f)
    
    # Write to prometheus text file for Alloy
    prom_metrics_path = "/var/lib/alloy/model_usage.prom"
    with open(prom_metrics_path, "w") as f:
        f.write("# HELP hermes_model_tokens_used Total tokens used by model\n")
        f.write("# TYPE hermes_model_tokens_used gauge\n")
        for m in models:
            # Sanitize model name for prometheus label
            label = m['name'].replace('/', '_').replace('-', '_')
            f.write(f'hermes_model_tokens_used{{model="{m["name"]}"}} {m.get("usage", 0)}\n')

    print(f"Updated fallback_models in {CONFIG_PATH} and metrics in {prom_metrics_path}.")

if __name__ == "__main__":
    update_fallback_order()
