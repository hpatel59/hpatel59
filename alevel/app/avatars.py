"""Generate anonymous student avatars: a memorable name plus a 4-digit PIN.

    python3 avatars.py 60 > avatars.csv

The teacher keeps the only record of which student has which avatar (offline).
"""
import random, secrets, sys

ADJ = ["Amber", "Arctic", "Azure", "Blaze", "Bold", "Brisk", "Cobalt", "Copper", "Coral", "Cosmic",
       "Crimson", "Crystal", "Dusk", "Ember", "Emerald", "Frost", "Golden", "Granite", "Hazel", "Indigo",
       "Iron", "Jade", "Jet", "Lunar", "Maple", "Misty", "Nimble", "Noble", "Onyx", "Polar",
       "Quartz", "Quick", "Rapid", "Ruby", "Rustic", "Sable", "Scarlet", "Silver", "Solar", "Steady",
       "Storm", "Swift", "Teal", "Thunder", "Topaz", "Velvet", "Vivid", "Wild", "Winter", "Zesty"]
ANIMAL = ["Badger", "Bison", "Condor", "Coyote", "Crane", "Dolphin", "Eagle", "Falcon", "Ferret", "Finch",
          "Fox", "Gecko", "Hare", "Hawk", "Heron", "Ibis", "Jaguar", "Kestrel", "Koala", "Lemur",
          "Lynx", "Marten", "Merlin", "Mongoose", "Moose", "Narwhal", "Ocelot", "Orca", "Osprey", "Otter",
          "Owl", "Panda", "Panther", "Pelican", "Puffin", "Puma", "Raven", "Robin", "Salmon", "Seal",
          "Stoat", "Swan", "Tapir", "Tiger", "Toucan", "Walrus", "Weasel", "Wolf", "Wombat", "Yak"]


def generate(n, taken=()):
    rng = random.SystemRandom()
    names = set(taken)
    out = []
    while len(out) < n:
        name = rng.choice(ADJ) + rng.choice(ANIMAL)
        if name in names:
            continue
        names.add(name)
        out.append((name, f"{secrets.randbelow(10000):04d}"))
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print("avatar,pin,student (fill in yourself - keep this file private)")
    for name, pin in generate(n):
        print(f"{name},{pin},")
