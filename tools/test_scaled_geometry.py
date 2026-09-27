"""Exercise the real CLI geometry comparisons without running their browsers."""

import ast
from copy import deepcopy
from pathlib import Path
import unittest

from verification_support import assert_near


def comparison(tool):
    source = Path(__file__).with_name(f'verify-{tool}-percentages.py')
    tree = ast.parse(source.read_text())
    near = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'near')
    namespace = {'assert_near': assert_near}
    if tool == 'viewport':
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        check = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == 'check_geometry')
        exec(compile(ast.Module(body=[near, check], type_ignores=[]), str(source), 'exec'), namespace)
        return lambda old, new: namespace['check_geometry'](old, new, 1600, 720)
    block = next(n for n in tree.body if isinstance(n, ast.With))
    start = next(i for i, n in enumerate(block.body) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'original' for t in n.targets)) + 1
    end = next(i for i in range(start, len(block.body)) if isinstance(block.body[i], ast.Expr)
               and isinstance(block.body[i].value, ast.Call)
               and isinstance(block.body[i].value.func, ast.Name)
               and block.body[i].value.func.id == 'print')
    code = compile(ast.Module(body=[near, *block.body[start:end]], type_ignores=[]), str(source), 'exec')
    return lambda old, new: exec(code, dict(namespace, original=old, scaled=new))


class ScaledGeometryTests(unittest.TestCase):
    def check_case(self, tool, case):
        old = [
            {'type': 'Rect', 'fill': 'blue', 'stroke': 'black', 'x': 192, 'y': 108,
             'width': 96, 'height': 54,
             'points': [{'x': 192, 'y': 108}, {'x': 288, 'y': 108}, {'x': 288, 'y': 162}]},
            {'type': 'Triangle', 'fill': 'red', 'stroke': 'black', 'x': 960, 'y': 540,
             'side': 108, 'points': [{'x': 960, 'y': 432}, {'x': 852, 'y': 594}, {'x': 1068, 'y': 594}]},
        ]
        new = deepcopy(old)
        for a, b in zip(old, new):
            b['x'] = a['x'] * 1600/1920
            b['y'] = a['y'] * 720/1080
            for key in ['width', 'height', 'side']:
                if key in a:
                    b[key] = a[key] * (1600/1920 if key == 'width' else 720/1080)
            for p, q in zip(a['points'], b['points']):
                q['x'] = b['x'] + (p['x']-a['x'])*720/1080 if a['type'] == 'Triangle' else p['x']*1600/1920
                q['y'] = p['y']*720/1080
        if case == 'missing_objects': new.pop()
        elif case == 'extra_objects': new.append(deepcopy(new[0]))
        elif case == 'empty_objects': new.clear()
        elif case == 'missing_points': new[0]['points'].pop()
        elif case == 'extra_points': new[0]['points'].append(deepcopy(new[0]['points'][0]))
        elif case == 'empty_points': new[0]['points'].clear()
        elif case == 'wrong_axis': new[1]['points'][1]['x'] = old[1]['points'][1]['x']*1600/1920
        elif case == 'within_tolerance': new[0]['x'] += 1e-11
        check = comparison(tool)
        if case in ['valid_scaled', 'within_tolerance']:
            check(old, new)
            result = 'accepted'
        else:
            marker = 'raw object count mismatch' if 'objects' in case else 'polygon point count mismatch'
            if case == 'wrong_axis':
                with self.assertRaises(AssertionError): check(old, new)
            else:
                with self.assertRaisesRegex(AssertionError, marker): check(old, new)
            result = 'rejected'
        print(f'PASS verify-{tool}-percentages.py {case}: {result}', flush=True)


for tool in ['frame', 'viewport']:
    for case in ['missing_objects', 'extra_objects', 'empty_objects', 'missing_points',
                 'extra_points', 'empty_points', 'valid_scaled', 'wrong_axis', 'within_tolerance']:
        def test(self, tool=tool, case=case):
            self.check_case(tool, case)
        setattr(ScaledGeometryTests, f'test_{tool}_{case}', test)


if __name__ == '__main__':
    unittest.main()
