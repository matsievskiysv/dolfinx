# Copyright (C) 2021 Jørgen S. Dokken
#
# This file is part of DOLFINX (https://www.fenicsproject.org)
#
# SPDX-License-Identifier:    LGPL-3.0-or-later

import os

import numpy as np
import pytest
import ufl
from dolfinx import Function, FunctionSpace, VectorFunctionSpace
from dolfinx.cpp.io import FidesWriter, VTXWriter, has_adios2
from dolfinx.generation import UnitCubeMesh, UnitSquareMesh
from dolfinx.mesh import CellType, create_mesh
from dolfinx_utils.test.fixtures import tempdir
from mpi4py import MPI

assert (tempdir)


@pytest.mark.skipif(MPI.COMM_WORLD.size > 1, reason="This test should only be run in serial.")
@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
def test_second_order_fides(tempdir):
    """Check that fides throws error on second order mesh"""
    filename = os.path.join(tempdir, "mesh_fides.bp")
    points = np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, 0]], dtype=np.float64)
    cells = np.array([[0, 1, 2]], dtype=np.int32)
    cell = ufl.Cell("interval", geometric_dimension=points.shape[1])
    domain = ufl.Mesh(ufl.VectorElement("Lagrange", cell, 2))
    mesh = create_mesh(MPI.COMM_WORLD, cells, points, domain)
    with pytest.raises(RuntimeError):
        FidesWriter(mesh.mpi_comm(), filename, mesh)


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
def test_functions_from_different_meshes_fides(tempdir):
    """Check that the underlying ADIOS2Writer catches sending in
    functions on different meshes"""
    filename = os.path.join(tempdir, "mesh_fides.bp")
    mesh0 = UnitSquareMesh(MPI.COMM_WORLD, 5, 5)
    mesh1 = UnitSquareMesh(MPI.COMM_WORLD, 10, 2)
    u0 = Function(FunctionSpace(mesh0, ("Lagrange", 1)))
    u1 = Function(FunctionSpace(mesh1, ("Lagrange", 1)))
    with pytest.raises(RuntimeError):
        FidesWriter(mesh0.mpi_comm(), filename, [u0._cpp_object, u1._cpp_object])


def generate_mesh(dim: int, simplex: bool, N: int = 3):
    """Helper function for parametrizing over meshes"""
    if dim == 2:
        if simplex:
            return UnitSquareMesh(MPI.COMM_WORLD, N, N)
        else:
            return UnitSquareMesh(MPI.COMM_WORLD, N, N, CellType.quadrilateral)
    elif dim == 3:
        if simplex:
            return UnitCubeMesh(MPI.COMM_WORLD, N, N, N)
        else:
            return UnitCubeMesh(MPI.COMM_WORLD, N, N, N, CellType.hexahedron)
    else:
        raise RuntimeError("Unsupported dimension")


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_fides_mesh(tempdir, dim, simplex):
    """ Test writing of a single Fides mesh with changing geometry"""
    filename = os.path.join(tempdir, "mesh_fides.bp")
    mesh = generate_mesh(dim, simplex)
    with FidesWriter(mesh.mpi_comm(), filename, mesh) as f:
        f.write(0.0)
        mesh.geometry.x[:, 1] += 0.1
        f.write(0.1)


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_mixed_fides_functions(tempdir, dim, simplex):
    """Test saving P2 and P1 functions with Fides"""
    mesh = generate_mesh(dim, simplex)
    v = Function(VectorFunctionSpace(mesh, ("Lagrange", 2)))
    q = Function(FunctionSpace(mesh, ("Lagrange", 1)))
    filename = os.path.join(tempdir, "v.bp")
    with pytest.raises(RuntimeError):
        FidesWriter(mesh.mpi_comm(), filename, [v._cpp_object, q._cpp_object])


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_two_fides_functions(tempdir, dim, simplex):
    """Test saving two functions with Fides"""
    mesh = generate_mesh(dim, simplex)
    v = Function(VectorFunctionSpace(mesh, ("Lagrange", 1)))
    q = Function(FunctionSpace(mesh, ("Lagrange", 1)))
    filename = os.path.join(tempdir, "v.bp")
    with FidesWriter(mesh.mpi_comm(), filename, [v._cpp_object, q._cpp_object]) as f:
        f.write(0)

        def vel(x):
            values = np.zeros((dim, x.shape[1]))
            values[0] = x[1]
            values[1] = x[0]
            return values
        v.interpolate(vel)
        q.interpolate(lambda x: x[0])
        f.write(1)


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_fides_function_at_nodes(tempdir, dim, simplex):
    """Test saving P1 functions with Fides (with changing geometry)"""
    mesh = generate_mesh(dim, simplex)
    v = Function(VectorFunctionSpace(mesh, ("Lagrange", 1)))
    q = Function(FunctionSpace(mesh, ("Lagrange", 1)))

    filename = os.path.join(tempdir, "v.bp")
    with FidesWriter(mesh.mpi_comm(), filename, [v._cpp_object, q._cpp_object]) as f:
        for t in [0.1, 0.5, 1]:
            # Only change one function
            q.interpolate(lambda x: t * (x[0] - 0.5)**2)
            f.write(t)

            mesh.geometry.x[:, :2] += 0.1
            if mesh.geometry.dim == 2:
                v.interpolate(lambda x: (t * x[0], x[1] + x[1] * 1j))
            elif mesh.geometry.dim == 3:
                v.interpolate(lambda x: (t * x[2], x[0] + x[2] * 2j, x[1]))
            f.write(t)


@pytest.mark.skipif(MPI.COMM_WORLD.size > 1, reason="This test should only be run in serial.")
@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
def test_second_order_vtx(tempdir):
    filename = os.path.join(tempdir, "mesh_fides.bp")
    points = np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, 0]], dtype=np.float64)
    cells = np.array([[0, 1, 2]], dtype=np.int32)
    cell = ufl.Cell("interval", geometric_dimension=points.shape[1])
    domain = ufl.Mesh(ufl.VectorElement("Lagrange", cell, 2))
    mesh = create_mesh(MPI.COMM_WORLD, cells, points, domain)
    with VTXWriter(mesh.mpi_comm(), filename, mesh) as f:
        f.write(0.0)


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_vtx_mesh(tempdir, dim, simplex):
    filename = os.path.join(tempdir, "mesh_vtx.bp")
    mesh = generate_mesh(dim, simplex)
    with VTXWriter(mesh.mpi_comm(), filename, mesh) as f:
        f.write(0.0)
        mesh.geometry.x[:, 1] += 0.1
        f.write(0.1)


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_vtx_functions_fail(tempdir, dim, simplex):
    "Test saving high order Lagrange functions"
    mesh = generate_mesh(dim, simplex)
    v = Function(VectorFunctionSpace(mesh, ("Lagrange", 2)))
    w = Function(FunctionSpace(mesh, ("Lagrange", 1)))
    filename = os.path.join(tempdir, "v.bp")
    with pytest.raises(RuntimeError):
        VTXWriter(mesh.mpi_comm(), filename, [v._cpp_object, w._cpp_object])


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_vtx_different_meshes_function(tempdir, dim, simplex):
    "Test saving  first order Lagrange functions"
    mesh = generate_mesh(dim, simplex)
    v = Function(FunctionSpace(mesh, ("Lagrange", 1)))
    mesh2 = generate_mesh(dim, simplex)
    w = Function(FunctionSpace(mesh2, ("Lagrange", 1)))
    filename = os.path.join(tempdir, "v.bp")
    with pytest.raises(RuntimeError):
        VTXWriter(mesh.mpi_comm(), filename, [v._cpp_object, w._cpp_object])


@pytest.mark.skipif(not has_adios2, reason="Requires ADIOS2.")
@pytest.mark.parametrize("dim", [2, 3])
@pytest.mark.parametrize("simplex", [True, False])
def test_vtx_functions(tempdir, dim, simplex):
    "Test saving high order Lagrange functions"
    mesh = generate_mesh(dim, simplex)
    V = VectorFunctionSpace(mesh, ("DG", 2))
    v = Function(V)
    bs = V.dofmap.index_map_bs

    def vel(x):
        values = np.zeros((dim, x.shape[1]))
        values[0] = x[1]
        values[1] = x[0]
        return values
    v.interpolate(vel)

    W = FunctionSpace(mesh, ("DG", 2))
    w = Function(W)
    w.interpolate(lambda x: x[0] + x[1])

    filename = os.path.join(tempdir, "v.bp")
    f = VTXWriter(mesh.mpi_comm(), filename, [v._cpp_object, w._cpp_object])

    # Set two cells to 0
    for c in [0, 1]:
        dofs = np.asarray([V.dofmap.cell_dofs(c) * bs + b for b in range(bs)], dtype=np.int32)
        v.x.array[dofs] = 0
        w.x.array[W.dofmap.cell_dofs(c)] = 1
    v.x.scatter_forward()
    w.x.scatter_forward()

    # Save twice and update geometry
    for t in [0.1, 1]:
        mesh.geometry.x[:, :2] += 0.1
        f.write(t)

    f.close()
