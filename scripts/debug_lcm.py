import sys; sys.path.insert(0, '/app/src')
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.lineup import _unit_cost, approx_lcm_budget
import random

repo = UnitRepo.get()

u1 = repo.get_by_id('janissary')
u2 = repo.get_by_id('dacoit')

if u1 and u2:
    c1 = _unit_cost(u1)
    c2 = _unit_cost(u2)
    print(f'{u1.name}: resource={sum(u1.cost.values())} pop={u1.pop} _unit_cost={c1}')
    print(f'{u2.name}: resource={sum(u2.cost.values())} pop={u2.pop} _unit_cost={c2}')
    lcm = approx_lcm_budget(c1, c2, 10000)
    print(f'LCM budget: {lcm}  count_a={lcm//c1} total_a={lcm//c1*c1}  count_b={lcm//c2} total_b={lcm//c2*c2}')
else:
    print('units not found')
    # try alternative IDs
    for uid in ['ypjanissary', 'dejanissary', 'ottomangunpowdermilitia', 'dacoit', 'thug', 'maratha']:
        u = repo.get_by_id(uid)
        if u:
            print(f'  found: {uid} -> {u.name} cost={_unit_cost(u)}')
