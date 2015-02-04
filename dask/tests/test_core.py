from dask.utils import raises
from dask.core import (istask, get, get_dependencies, cull, flatten, fuse,
                       subs, inline)


def contains(a, b):
    """

    >>> contains({'x': 1, 'y': 2}, {'x': 1})
    True
    >>> contains({'x': 1, 'y': 2}, {'z': 3})
    False
    """
    return all(a.get(k) == v for k, v in b.items())

def inc(x):
    return x + 1

def add(x, y):
    return x + y


def test_istask():
    assert istask((inc, 1))
    assert not istask(1)
    assert not istask((1, 2))


d = {':x': 1,
     ':y': (inc, ':x'),
     ':z': (add, ':x', ':y')}


def test_get():
    assert get(d, ':x') == 1
    assert get(d, ':y') == 2
    assert get(d, ':z') == 3


def test_memoized_get():
    try:
        import toolz
    except ImportError:
        return
    cache = dict()
    getm = toolz.memoize(get, cache=cache, key=lambda args, kwargs: args[1:])

    result = getm(d, ':z', get=getm)
    assert result == 3

    assert contains(cache, {(':x',): 1,
                            (':y',): 2,
                            (':z',): 3})

def test_data_not_in_dict_is_ok():
    d = {'x': 1, 'y': (add, 'x', 10)}
    assert get(d, 'y') == 11


def test_get_with_list():
    d = {'x': 1, 'y': 2, 'z': (sum, ['x', 'y'])}

    assert get(d, ['x', 'y']) == [1, 2]
    assert get(d, 'z') == 3


def test_get_with_nested_list():
    d = {'x': 1, 'y': 2, 'z': (sum, ['x', 'y'])}

    assert get(d, [['x'], 'y']) == [[1], 2]
    assert get(d, 'z') == 3


def test_get_works_with_unhashables_in_values():
    f = lambda x, y: x + len(y)
    d = {'x': 1, 'y': (f, 'x', set([1]))}

    assert get(d, 'y') == 2


def test_get_laziness():
    def isconcrete(arg):
        return isinstance(arg, list)

    d = {'x': 1, 'y': 2, 'z': (isconcrete, ['x', 'y'])}

    assert get(d, ['x', 'y']) == [1, 2]
    assert get(d, 'z') == False


def test_get_dependencies_nested():
    dsk = {'x': 1, 'y': 2,
           'z': (add, (inc, [['x']]), 'y')}

    assert get_dependencies(dsk, 'z') == set(['x', 'y'])


def test_get_dependencies_empty():
    dsk = {'x': (inc,)}
    assert get_dependencies(dsk, 'x') == set()


def test_nested_tasks():
    d = {'x': 1,
         'y': (inc, 'x'),
         'z': (add, (inc, 'x'), 'y')}

    assert get(d, 'z') == 4


def test_cull():
    # 'out' depends on 'x' and 'y', but not 'z'
    d = {'x': 1, 'y': (inc, 'x'), 'z': (inc, 'x'), 'out': (add, 'y', 10)}
    culled = cull(d, 'out')
    assert culled == {'x': 1, 'y': (inc, 'x'), 'out': (add, 'y', 10)}
    assert cull(d, 'out') == cull(d, ['out'])
    assert cull(d, ['out', 'z']) == d
    assert cull(d, [['out'], ['z']]) == cull(d, ['out', 'z'])
    assert raises(KeyError, lambda: cull(d, 'badkey'))


def test_get_stack_limit():
    d = dict(('x%s' % (i+1), (inc, 'x%s' % i)) for i in range(10000))
    d['x0'] = 0
    assert get(d, 'x10000') == 10000
    # introduce cycle
    d['x5000'] = (inc, 'x5001')
    assert raises(RuntimeError, lambda: get(d, 'x10000'))
    assert get(d, 'x4999') == 4999


def test_flatten():
    assert list(flatten(())) == []


def test_subs():
    assert subs((sum, [1, 'x']), 'x', 2) == (sum, [1, 2])
    assert subs((sum, [1, ['x']]), 'x', 2) == (sum, [1, [2]])


def test_fuse():
    assert fuse({
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2,
    }) == {
        'w': (inc, (inc, (inc, (add, 'a', 'b')))),
        'a': 1,
        'b': 2,
    }
    assert fuse({
        'NEW': (inc, 'y'),
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2,
    }) == {
        'NEW': (inc, 'y'),
        'w': (inc, (inc, 'y')),
        'y': (inc, (add, 'a', 'b')),
        'a': 1,
        'b': 2,
    }
    assert fuse({
        'v': (inc, 'y'),
        'u': (inc, 'w'),
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': (inc, 'c'),
        'b': (inc, 'd'),
        'c': 1,
        'd': 2,
    }) == {
        'u': (inc, (inc, (inc, 'y'))),
        'v': (inc, 'y'),
        'y': (inc, (add, 'a', 'b')),
        'a': (inc, 1),
        'b': (inc, 2),
    }
    assert fuse({
        'a': (inc, 'x'),
        'b': (inc, 'x'),
        'c': (inc, 'x'),
        'd': (inc, 'c'),
        'x': (inc, 'y'),
        'y': 0,
    }) == {
        'a': (inc, 'x'),
        'b': (inc, 'x'),
        'd': (inc, (inc, 'x')),
        'x': (inc, 0),
    }
    assert fuse({
        'a': 1,
        'b': (inc, 'a'),
        'c': (add, 'b', 'b')
    }) == {
        'b': (inc, 1),
        'c': (add, 'b', 'b')
    }

def test_inline():
    d = {'a': 1, 'b': (inc, 'a'), 'c': (inc, 'b'), 'd': (add, 'a', 'c')}
    assert inline(d) == {'b': (inc, 1), 'c': (inc, 'b'), 'd': (add, 1, 'c')}
    assert inline(d, ['a', 'b', 'c']) == {'d': (add, 1, (inc, (inc, 1)))}

    d = {'x': 1, 'y': (inc, 'x'), 'z': (add, 'x', 'y')}
    assert inline(d) == {'y': (inc, 1), 'z': (add, 1, 'y')}
    assert inline(d, keys='y') == {'z': (add, 1, (inc, 1))}
    assert inline(d, keys='y', inline_constants=False) == {
        'x': 1, 'z': (add, 'x', (inc, 'x'))}