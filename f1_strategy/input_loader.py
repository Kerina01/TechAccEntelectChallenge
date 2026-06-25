import json

def load_level(path):
    with open(path, "r") as file:
        return json.load(file)