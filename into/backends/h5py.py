from __future__ import absolute_import, division, print_function

import datashape
from datashape import (DataShape, Record, Mono, dshape, to_numpy,
                       to_numpy_dtype, discover)
from datashape.predicates import isrecord, iscollection
from datashape.dispatch import dispatch
import h5py
import numpy as np
from toolz import assoc, keyfilter
from collections import Iterator
import os

from ..append import append
from ..convert import convert, ooc_types
from ..create import create
from ..drop import drop
from ..cleanup import cleanup
from ..resource import resource, resource_matches
from ..chunks import chunks, Chunks
from ..compatibility import unicode
from into.backends.hdf import HDFFile, HDFTable

h5py_attributes = ['chunks', 'compression', 'compression_opts', 'dtype',
                   'fillvalue', 'fletcher32', 'maxshape', 'shape']


@discover.register((h5py.Group, h5py.File))
def discover_h5py_group_file(g):
    return DataShape(Record([[k, discover(v)] for k, v in g.items()]))


@discover.register(h5py.Dataset)
def discover_h5py_dataset(d):
    s = str(datashape.from_numpy(d.shape, d.dtype))
    return dshape(s.replace('object', 'string'))


def varlen_dtype(dt):
    """ Inject variable length string element for 'O' """
    if "'O'" not in str(dt):
        return dt
    varlen = h5py.special_dtype(vlen=unicode)
    return np.dtype(eval(str(dt).replace("'O'", 'varlen')))


def dataset_from_dshape(file, datapath, ds, **kwargs):
    dtype = varlen_dtype(to_numpy_dtype(ds))
    if datashape.var not in list(ds):
        shape = to_numpy(ds)[0]
    elif datashape.var not in list(ds)[1:]:
        shape = (0,) + to_numpy(ds.subshape[0])[0]
    else:
        raise ValueError("Don't know how to handle varlen nd shapes")

    if shape:
        kwargs['chunks'] = kwargs.get('chunks', True)
        kwargs['maxshape'] = kwargs.get('maxshape', (None,) + shape[1:])

    kwargs2 = keyfilter(h5py_attributes.__contains__, kwargs)
    try:
        return file.require_dataset(datapath, shape=shape, dtype=dtype, **kwargs2)
    except TypeError as e:
        # we have a shape mismatch
        # all dims must match except ndim=0 (the appending dim)
        existing_shape = file[datapath].shape
        if not (shape[1:] == existing_shape[1:]):
            raise


def create_from_datashape(group, ds, name=None, **kwargs):

    ds = dshape(ds)
    assert isrecord(ds)
    if isinstance(ds, DataShape) and len(ds) == 1:
        ds = ds[0]
    for name, sub_ds in ds.dict.items():
        if isrecord(sub_ds):
            g = group.require_group(name)
            create_from_datashape(g, sub_ds, **kwargs)
        else:
            dataset_from_dshape(file=group.file,
                                datapath='/'.join([group.name, name]),
                                ds=sub_ds, **kwargs)


@create.register(h5py.File, object)
def create(f, pathname, dshape=None, **kwargs):
    try:
        f.close()
    except:
        pass

    f = h5py.File(pathname)
    if dshape is not None:
        create_from_datashape(f, dshape, **kwargs)
    return f


@resource.register('^(h5py://)?.+\.(h5|hdf5)', priority=10.0)
def resource_h5py(uri, datapath=None, dshape=None, **kwargs):

    uri = resource_matches(uri, 'h5py')

    olddatapath = datapath

    if dshape is not None:
        ds = datashape.dshape(dshape)
        if datapath is not None:
            while ds and datapath:
                datapath, name = datapath.rsplit('/', 1)
                ds = Record([[name, ds]])
            ds = datashape.dshape(ds)
        f = create(h5py.File, pathname=uri, dshape=ds, **kwargs)
    else:
        f = h5py.File(uri)
        ds = discover(f)

    if olddatapath is not None:
        return HDFTable(HDFFile(f), olddatapath)

    return HDFFile(f)


@drop.register((h5py.Group, h5py.Dataset))
def drop_group(h):
    del h.file[h.name]


@dispatch(h5py.File)
def pathname(f):
    return f.filename


@dispatch(h5py.File)
def dialect(f):
    return 'h5py'


@dispatch(h5py.File)
def get_table(f, datapath, **kwargs):
    assert datapath is not None
    return f[datapath]


@cleanup.register(h5py.File)
def cleanup_file(f):
    try:
        f.close()
    except:
        pass


@cleanup.register(h5py.Dataset)
def cleanup_dataset(dset):
    dset.file.close()


@append.register(h5py.Dataset, np.ndarray)
def append_h5py(dset, x, **kwargs):

    if not sum(x.shape):
        return dset
    shape = list(dset.shape)
    shape[0] += len(x)
    dset.resize(shape)
    dset[-len(x):] = x
    return dset


@append.register(h5py.Dataset, chunks(np.ndarray))
def append_h5py_dset_chunks(dset, c, **kwargs):

    for chunk in c:
        append_h5py(dset, chunk)
    return dset


@append.register(h5py.Dataset, object)
def append_h5py_dset(dset, x, **kwargs):

    converted = convert(chunks(np.ndarray), x, **kwargs)
    return append_h5py_dset_chunks(dset, converted, **kwargs)


@convert.register(np.ndarray, h5py.Dataset, cost=3.0)
def h5py_to_numpy(dset, force=False, **kwargs):
    if dset.size > 1e9:
        raise MemoryError("File size is large: %0.2f GB.\n"
                          "Convert with flag force=True to force loading" %
                          dset.size / 1e9)
    else:
        return dset[:]


@convert.register(chunks(np.ndarray), h5py.Dataset, cost=3.0)
def h5py_to_numpy_chunks(t, chunksize=2 ** 20, **kwargs):
    return chunks(np.ndarray)(h5py_to_numpy_iterator(t, chunksize=chunksize, **kwargs))


@convert.register(Iterator, h5py.Dataset, cost=5.0)
def h5py_to_numpy_iterator(t, chunksize=1e7, **kwargs):
    """ return the embedded iterator """

    chunksize = int(chunksize)
    for i in range(0, t.shape[0], chunksize):
        yield t[i: i + chunksize]

ooc_types.add(h5py.Dataset)
