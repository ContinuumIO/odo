from __future__ import absolute_import, division, print_function

from toolz import identity
from toolz.compatibility import zip
from datashape import (discover, float32, float64, Option, String, from_numpy,
                       Record)

import pandas as pd


possibly_missing = frozenset((float32, float64))


@discover.register(pd.DataFrame)
def discover_dataframe(df):
    names = list(df.columns)
    dtypes = [discover(df[c]).measure for c in names]
    odtypes = [Option(dt) if dt in possibly_missing else dt for dt in dtypes]
    return len(df) * Record(list(zip(names, odtypes)))


@discover.register(pd.Series)
def discover_series(s):
    typ = pd.lib.infer_dtype(s)
    if typ == 'unicode' or typ == 'string':
        nchars = pd.lib.max_len_string_array(s.values)
        option = Option if s.isnull().any() else identity
        measure = String(nchars) if typ == 'unicode' else String(nchars, 'A')
    elif typ.startswith(('timedelta', 'datetime')):
        option = Option if s.isnull().any() else identity
        measure = from_numpy((), s.dtype)
    else:
        option = identity
        measure = from_numpy((), s.dtype)
    return len(s) * option(measure)


def coerce_datetimes(df):
    """ Make object columns into datetimes if possible

    Warning: this operates inplace.

    Example
    -------

    >>> df = pd.DataFrame({'dt': ['2014-01-01'], 'name': ['Alice']})
    >>> df.dtypes  # note that these are strings/object
    dt      object
    name    object
    dtype: object

    >>> df2 = coerce_datetimes(df)
    >>> df2
              dt   name
    0 2014-01-01  Alice

    >>> df2.dtypes  # note that only the datetime-looking-one was transformed
    dt      datetime64[ns]
    name            object
    dtype: object
    """
    df2 = df.select_dtypes(include=['object']).apply(pd.to_datetime)
    for c in df2.columns:
        df[c] = df2[c]
    return df
