# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that sm3_interface.py compiles to the same program as the bytecode shipped before it.

Until 2026-10-12 the main window of SM3 Studio was only distributed as a marshalled code object,
sm3_studio_original.marshal, bundled in SM3 Studio.exe. sm3_interface.py replaces it. This script
compiles sm3_interface.py and compares it, code object by code object, with that bytecode.

    python construire/verify_interface.py "<old SM3 Studio.exe>"       (builds of 2026-09-09 .. 2026-10-08)
    python construire/verify_interface.py sm3_studio_original.marshal

Requirements: Python 3.14 (bytecode differs between Python versions); PyInstaller only to read an
.exe. With an .exe, the comparison is also made for the English interface: the old bytecode goes
through the old studio_language.py bundled in that .exe, the new source through the repository's.
Only the builds of 2026-10-06 to 2026-10-08 have today's translation table: older ones did not yet
translate 'Dossier du jeu', 'celui qui contient Game.exe' and 'Tous les fichiers', so they show
differences in the English check only (module constants and Studio._onglet_chemins).

What must be equal, for every function, class body and the module: the instructions (opcode and
argument, constants resolved to their values), the constants, the names, the local / cell / free
variables, the argument counts, the flags, the stack size and the exception table.
What may differ: line numbers, the file name, docstrings (function docstrings, and the module /
class docstrings stored by `LOAD_CONST; STORE_NAME __doc__`), a class's __firstlineno__, and an
unreferenced co_consts[0] that CPython keeps in functions without a docstring.
Exit code 0 when no behavioural difference is found.
"""
import dis
import importlib.util
import marshal
import os
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CO_HAS_DOCSTRING = 0x4000000   # Python 3.14: the function has a docstring in co_consts[0]


def const_key(value):
    """Comparison key that keeps types apart (1, 1.0 and True are different constants)."""
    if isinstance(value, types.CodeType):
        return ('code', value.co_qualname)
    if isinstance(value, (tuple, frozenset)):
        items = [const_key(v) for v in value]
        if isinstance(value, frozenset):
            items.sort(key=repr)
        return (type(value).__name__, tuple(items))
    if isinstance(value, float):
        return ('float', value.hex())
    if isinstance(value, slice):
        return ('slice', const_key(value.start), const_key(value.stop), const_key(value.step))
    return (type(value).__name__, value)


def canonical(code):
    """Instructions and constants of one code object, with the tolerated items neutralised."""
    ins = list(dis.get_instructions(code))
    tolerated_idx, used_idx, out = set(), set(), []
    for k, i in enumerate(ins):
        nxt = ins[k + 1] if k + 1 < len(ins) else None
        if (nxt is not None and nxt.opname == 'STORE_NAME'
                and nxt.argval in ('__doc__', '__firstlineno__')
                and i.opname in ('LOAD_CONST', 'LOAD_SMALL_INT')):
            out.append((i.offset, 'TOLERATED', nxt.argval))
            if i.opname == 'LOAD_CONST':
                tolerated_idx.add(i.arg)
            continue
        if i.opname == 'LOAD_CONST':
            used_idx.add(i.arg)
            arg = const_key(i.argval)
        elif i.opcode in dis.hasjrel or i.opcode in dis.hasjabs:
            arg = ('jump', i.argval)
        elif isinstance(i.argval, types.CodeType):
            arg = ('code', i.argval.co_qualname)
        elif i.argval is None:
            arg = i.arg
        else:
            arg = repr(i.argval)
        out.append((i.offset, i.opname, arg))
    has_doc = bool(code.co_flags & CO_HAS_DOCSTRING)
    skip_first = has_doc or (code.co_consts and 0 not in used_idx and 0 not in tolerated_idx)
    consts = []
    for idx, c in enumerate(code.co_consts):
        if idx == 0 and skip_first:
            continue
        consts.append(('TOLERATED',) if idx in tolerated_idx and idx not in used_idx else const_key(c))
    return out, consts


def compare(a, b, differences, where=''):
    """Recursive comparison; returns the number of code objects compared."""
    where = where + '/' + a.co_qualname
    for field in ('co_name', 'co_qualname', 'co_argcount', 'co_posonlyargcount',
                  'co_kwonlyargcount', 'co_nlocals', 'co_stacksize', 'co_names', 'co_varnames',
                  'co_cellvars', 'co_freevars', 'co_exceptiontable'):
        if getattr(a, field) != getattr(b, field):
            differences.append((where, field))
    if (a.co_flags & ~CO_HAS_DOCSTRING) != (b.co_flags & ~CO_HAS_DOCSTRING):
        differences.append((where, 'co_flags'))
    ia, ca = canonical(a)
    ib, cb = canonical(b)
    if ia != ib:
        differences.append((where, 'instructions'))
    if ca != cb:
        differences.append((where, 'constants'))
    sub_a = [c for c in a.co_consts if isinstance(c, types.CodeType)]
    sub_b = [c for c in b.co_consts if isinstance(c, types.CodeType)]
    if len(sub_a) != len(sub_b):
        differences.append((where, 'number of nested functions/classes'))
    return 1 + sum(compare(x, y, differences, where) for x, y in zip(sub_a, sub_b))


def load_language(path, alias):
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(label, original, candidate):
    differences = []
    count = compare(original, candidate, differences)
    print('%s: %d code objects compared, %d behavioural difference(s)' % (label, count, len(differences)))
    for where, what in differences[:40]:
        print('    %s  [%s]' % (where, what))
    return not differences


def main(argv):
    if sys.version_info[:2] != (3, 14):
        sys.exit('Python 3.14 is required (bytecode is specific to one Python version).')
    if len(argv) != 1:
        sys.exit(__doc__)
    source_path = os.path.join(REPO, 'sm3_interface.py')
    with open(source_path, encoding='utf-8-sig') as f:
        candidate = compile(f.read(), source_path, 'exec')
    old_language = None
    if argv[0].lower().endswith('.exe'):
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(argv[0])
        if 'sm3_studio_original.marshal' not in archive.toc:
            sys.exit('This .exe does not bundle sm3_studio_original.marshal (built after 2026-10-08?).')
        original = marshal.loads(archive.extract('sm3_studio_original.marshal'))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'studio_language.py')
            with open(path, 'wb') as f:
                f.write(archive.extract('studio_language.py'))
            old_language = load_language(path, 'studio_language_old')
    else:
        with open(argv[0], 'rb') as f:
            original = marshal.load(f)
    ok = report('French interface', original, candidate)
    if old_language is not None:
        new_language = load_language(os.path.join(REPO, 'studio_language.py'), 'studio_language_new')
        ok &= report('English interface', old_language.localize(original),
                     new_language.localize(candidate))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
