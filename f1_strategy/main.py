from strategy import build_basic_strategy
from output_writer import write_submission
from input_loader import load_level

level = load_level("levels/level1.json")

strategy = build_basic_strategy(level)

write_submission(strategy, "outputs/submission.txt")