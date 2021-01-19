import math
import shutil
import time
from pathlib import Path

from jack.utilities import condense
from matplotlib import pyplot as plt


def get_eta(start_time, iters_completed, total_iters):
    time_elapsed = time.time() - start_time
    time_per_iter = time_elapsed / (iters_completed + 1)
    time_remaining = time_per_iter * (total_iters - iters_completed - 1)
    formatted_eta = format_time(time_remaining)
    return formatted_eta


def format_time(t):
    """Returns string continaing time in hh:mm:ss format.

    Arguments:
        t: time in seconds

    Raises:
        ValueError if t < 0
    """
    if t < 0:
        raise ValueError('Time must be positive.')

    t = int(math.floor(t))
    h = t // 3600
    m = (t - (h * 3600)) // 60
    s = t - ((h * 3600) + (m * 60))
    return '{0:02d}:{1:02d}:{2:02d}'.format(h, m, s)


class Timer:
    """Simple timer class.

    To time a block of code, wrap it like so:

        with Timer() as t:
            <some_code>
        total_time = t.interval

    The time taken for the code to execute is stored in t.interval.
    """

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.interval = self.end - self.start


def print_with_overwrite(*s, spacer=' '):
    """Prints to console, but overwrites previous output, rather than creating
    a newline.

    Arguments:
        s: string (possibly with multiple lines) to print
        spacer: whitespace character to use between words on each line
    """
    s = '\n'.join(
        [spacer.join([str(word) for word in substring]) for substring in s])
    ERASE = '\x1b[2K'
    UP_ONE = '\x1b[1A'
    lines = s.split('\n')
    n_lines = len(lines)
    console_width = shutil.get_terminal_size((0, 20)).columns
    for idx in range(n_lines):
        lines[idx] += ' ' * max(0, console_width - len(lines[idx]))
    print((ERASE + UP_ONE) * (n_lines - 1) + s, end='\r', flush=True)


def plot_with_smoothing(y, fname, gap=100):
    x, y = condense(y, gap=gap)
    fig, ax = plt.subplots(111)
    ax.plot(x, y, 'k-')
    plt.savefig(Path(fname).expanduser())