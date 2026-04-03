import os
import pickle
from classes.trackable import Trackable

SAVE_PATH = os.path.join(os.path.dirname(__file__), "save.pkl")

_held = None  # strong references keeping loaded objects alive in WeakSets

def save(player):
    data = {
        'player': player,
        'objects': tuple(Trackable.all_instances()),
    }
    with open(SAVE_PATH, 'wb') as f:
        pickle.dump(data, f)

def load():
    global _held
    with open(SAVE_PATH, 'rb') as f:
        data = pickle.load(f)
    objects = data['objects']
    _held = objects
    for obj in objects:
        type(obj)._instances.add(obj)
    return data['player']
