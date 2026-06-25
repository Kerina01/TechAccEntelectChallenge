import json

def write_submission(strategy, path):
    with open(path, "w") as file:
        json.dump(strategy, file, indent=2)