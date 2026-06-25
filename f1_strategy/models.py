from dataclasses import dataclass

@dataclass
class Car:
    max_speed: float
    acceleration: float
    braking: float
    crawl_speed: float
    limp_speed: float

@dataclass
class Segment:
    id: int
    type: str
    length: float
    radius: float | None = None

@dataclass
class Tyre:
    id: int
    type: str
    base_friction: float

@dataclass
class Race:
    laps: int
    corner_crash_penalty: float