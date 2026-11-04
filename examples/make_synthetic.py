"""Write a SYNTHETIC detector smoke-test only. NOT observational evidence."""
from pathlib import Path
import numpy as np
from signalwatch.radio import demo_power
out=Path('data')/'inbox'/'SYNTHETIC_TEST_ONLY.npz'
out.parent.mkdir(parents=True,exist_ok=True)
np.savez_compressed(out,power=demo_power())
print('Created SYNTHETIC test file:',out)
print('Remove this file and corresponding local test DB records before scientific use.')
