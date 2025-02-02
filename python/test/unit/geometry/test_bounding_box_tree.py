# Copyright (C) 2013-2021 Anders Logg, Jørgen S. Dokken, Chris Richardson
#
# This file is part of DOLFINx (https://www.fenicsproject.org)
#
# SPDX-License-Identifier:    LGPL-3.0-or-later
"""Unit tests for BoundingBoxTree"""

import numpy
import pytest
from dolfinx import (BoxMesh, UnitCubeMesh, UnitIntervalMesh, UnitSquareMesh,
                     cpp)
from dolfinx.geometry import (BoundingBoxTree, compute_closest_entity,
                              compute_colliding_cells, compute_collisions,
                              compute_distance_gjk, create_midpoint_tree)
from dolfinx.mesh import CellType, locate_entities, locate_entities_boundary
from dolfinx_utils.test.skips import skip_in_parallel
from mpi4py import MPI


def extract_geometricial_data(mesh, dim, entities):
    """For a set of entities in a mesh, return the coordinates of the vertices"""
    mesh_nodes = []
    geom = mesh.geometry
    g_indices = cpp.mesh.entities_to_geometry(mesh, dim,
                                              numpy.array(entities, dtype=numpy.int32),
                                              False)
    for cell in g_indices:
        nodes = numpy.zeros((len(cell), 3), dtype=numpy.float64)
        for j, entity in enumerate(cell):
            nodes[j] = geom.x[entity]
        mesh_nodes.append(nodes)
    return mesh_nodes


def expand_bbox(bbox):
    """Expand min max bbox to convex hull"""
    return numpy.array([[bbox[0][0], bbox[0][1], bbox[0][2]],
                        [bbox[0][0], bbox[0][1], bbox[1][2]],
                        [bbox[0][0], bbox[1][1], bbox[0][2]],
                        [bbox[1][0], bbox[0][1], bbox[0][2]],
                        [bbox[1][0], bbox[0][1], bbox[1][2]],
                        [bbox[1][0], bbox[1][1], bbox[0][2]],
                        [bbox[0][0], bbox[1][1], bbox[1][2]],
                        [bbox[1][0], bbox[1][1], bbox[1][2]]])


def find_colliding_cells(mesh, bbox):
    """Given a mesh and a bounding box((xmin, ymin, zmin), (xmax, ymax,
    zmax)) find all colliding cells"""

    # Find actual cells using known bounding box tree
    colliding_cells = []
    num_cells = mesh.topology.index_map(mesh.topology.dim).size_local
    x_indices = cpp.mesh.entities_to_geometry(
        mesh, mesh.topology.dim, numpy.arange(num_cells, dtype=numpy.int32), False)
    points = mesh.geometry.x
    bounding_box = expand_bbox(bbox)
    for cell in range(num_cells):
        vertex_coords = points[x_indices[cell]]
        bbox_cell = numpy.array([vertex_coords[0], vertex_coords[0]])
        # Create bounding box for cell
        for i in range(1, vertex_coords.shape[0]):
            for j in range(3):
                bbox_cell[0, j] = min(bbox_cell[0, j], vertex_coords[i, j])
                bbox_cell[1, j] = max(bbox_cell[1, j], vertex_coords[i, j])
        distance = compute_distance_gjk(expand_bbox(bbox_cell), bounding_box)
        if numpy.dot(distance, distance) < 1e-16:
            colliding_cells.append(cell)

    return colliding_cells


@pytest.mark.parametrize("padding", [True, False])
@skip_in_parallel
def test_padded_bbox(padding):
    """Test collision between two meshes separated by a distance of
    epsilon, and check if padding the mesh creates a possible
    collision"""
    eps = 1e-12
    x0 = numpy.array([0, 0, 0])
    x1 = numpy.array([1, 1, 1 - eps])
    mesh_0 = BoxMesh(MPI.COMM_WORLD, [x0, x1], [1, 1, 2], CellType.hexahedron)
    x2 = numpy.array([0, 0, 1 + eps])
    x3 = numpy.array([1, 1, 2])
    mesh_1 = BoxMesh(MPI.COMM_WORLD, [x2, x3], [1, 1, 2], CellType.hexahedron)
    if padding:
        pad = eps
    else:
        pad = 0

    bbox_0 = BoundingBoxTree(mesh_0, mesh_0.topology.dim, padding=pad)
    bbox_1 = BoundingBoxTree(mesh_1, mesh_1.topology.dim, padding=pad)
    collisions = compute_collisions(bbox_0, bbox_1)
    if padding:
        assert len(collisions) == 1
        # Check that the colliding elements are separated by a distance
        # 2*epsilon
        element_0 = extract_geometricial_data(mesh_0, mesh_0.topology.dim, [collisions[0][0]])[0]
        element_1 = extract_geometricial_data(mesh_1, mesh_1.topology.dim, [collisions[0][1]])[0]
        distance = numpy.linalg.norm(compute_distance_gjk(element_0, element_1))
        assert numpy.isclose(distance, 2 * eps)
    else:
        assert len(collisions) == 0


def rotation_matrix(axis, angle):
    # See https://en.wikipedia.org/wiki/Rotation_matrix,
    # Subsection: Rotation_matrix_from_axis_and_angle.
    if numpy.isclose(numpy.inner(axis, axis), 1):
        n_axis = axis
    else:
        # Normalize axis
        n_axis = axis / numpy.sqrt(numpy.inner(axis, axis))

    # Define cross product matrix of axis
    axis_x = numpy.array([[0, -n_axis[2], n_axis[1]],
                          [n_axis[2], 0, -n_axis[0]],
                          [-n_axis[1], n_axis[0], 0]])
    id = numpy.cos(angle) * numpy.eye(3)
    outer = (1 - numpy.cos(angle)) * numpy.outer(n_axis, n_axis)
    return numpy.sin(angle) * axis_x + id + outer


def test_empty_tree():
    mesh = UnitIntervalMesh(MPI.COMM_WORLD, 16)
    bbtree = BoundingBoxTree(mesh, mesh.topology.dim, [])
    assert bbtree.num_bboxes == 0


@skip_in_parallel
def test_compute_collisions_point_1d():
    N = 16
    p = numpy.array([0.3, 0, 0])
    mesh = UnitIntervalMesh(MPI.COMM_WORLD, N)
    dx = 1 / N
    cell_index = int(p[0] // dx)
    # Vertices of cell we should collide with
    vertices = numpy.array([[dx * cell_index, 0, 0], [dx * (cell_index + 1), 0, 0]])

    # Compute collision
    tdim = mesh.topology.dim
    tree = BoundingBoxTree(mesh, tdim)
    entities = compute_collisions(tree, p)
    assert len(entities.array) == 1

    # Get the vertices of the geometry
    geom_entities = cpp.mesh.entities_to_geometry(mesh, tdim, entities.array, False)[0]
    x = mesh.geometry.x
    cell_vertices = x[geom_entities]
    # Check that we get the cell with correct vertices
    assert numpy.allclose(cell_vertices, vertices)


@skip_in_parallel
@pytest.mark.parametrize("point", [numpy.array([0.52, 0, 0]),
                                   numpy.array([0.9, 0, 0])])
def test_compute_collisions_tree_1d(point):
    mesh_A = UnitIntervalMesh(MPI.COMM_WORLD, 16)

    def locator_A(x):
        return x[0] >= point[0]
    # Locate all vertices of mesh A that should collide
    vertices_A = cpp.mesh.locate_entities(mesh_A, 0, locator_A)
    mesh_A.topology.create_connectivity(0, mesh_A.topology.dim)
    v_to_c = mesh_A.topology.connectivity(0, mesh_A.topology.dim)

    # Find all cells connected to vertex in the collision bounding box
    cells_A = numpy.sort(numpy.unique(numpy.hstack([v_to_c.links(vertex) for vertex in vertices_A])))

    mesh_B = UnitIntervalMesh(MPI.COMM_WORLD, 16)
    bgeom = mesh_B.geometry.x
    bgeom += point

    def locator_B(x):
        return x[0] <= 1

    # Locate all vertices of mesh B that should collide
    vertices_B = cpp.mesh.locate_entities(mesh_B, 0, locator_B)
    mesh_B.topology.create_connectivity(0, mesh_B.topology.dim)
    v_to_c = mesh_B.topology.connectivity(0, mesh_B.topology.dim)

    # Find all cells connected to vertex in the collision bounding box
    cells_B = numpy.sort(numpy.unique(numpy.hstack([v_to_c.links(vertex) for vertex in vertices_B])))

    # Find colliding entities using bounding box trees
    tree_A = BoundingBoxTree(mesh_A, mesh_A.topology.dim)
    tree_B = BoundingBoxTree(mesh_B, mesh_B.topology.dim)
    entities = compute_collisions(tree_A, tree_B)
    entities_A = numpy.sort(numpy.unique([q[0] for q in entities]))
    entities_B = numpy.sort(numpy.unique([q[1] for q in entities]))
    assert numpy.allclose(entities_A, cells_A)
    assert numpy.allclose(entities_B, cells_B)


@skip_in_parallel
@pytest.mark.parametrize("point", [numpy.array([0.52, 0.51, 0.0]),
                                   numpy.array([0.9, -0.9, 0.0])])
def test_compute_collisions_tree_2d(point):
    mesh_A = UnitSquareMesh(MPI.COMM_WORLD, 3, 3)
    mesh_B = UnitSquareMesh(MPI.COMM_WORLD, 5, 5)
    bgeom = mesh_B.geometry.x
    bgeom += point
    tree_A = BoundingBoxTree(mesh_A, mesh_A.topology.dim)
    tree_B = BoundingBoxTree(mesh_B, mesh_B.topology.dim)
    entities = compute_collisions(tree_A, tree_B)

    entities_A = numpy.sort(numpy.unique([q[0] for q in entities]))
    entities_B = numpy.sort(numpy.unique([q[1] for q in entities]))
    cells_A = find_colliding_cells(mesh_A, tree_B.get_bbox(tree_B.num_bboxes - 1))
    cells_B = find_colliding_cells(mesh_B, tree_A.get_bbox(tree_A.num_bboxes - 1))
    assert numpy.allclose(entities_A, cells_A)
    assert numpy.allclose(entities_B, cells_B)


@skip_in_parallel
@pytest.mark.parametrize("point", [numpy.array([0.52, 0.51, 0.3]),
                                   numpy.array([0.9, -0.9, 0.3])])
def test_compute_collisions_tree_3d(point):
    mesh_A = UnitCubeMesh(MPI.COMM_WORLD, 2, 2, 2)
    mesh_B = UnitCubeMesh(MPI.COMM_WORLD, 2, 2, 2)

    bgeom = mesh_B.geometry.x
    bgeom += point

    tree_A = BoundingBoxTree(mesh_A, mesh_A.topology.dim)
    tree_B = BoundingBoxTree(mesh_B, mesh_B.topology.dim)
    entities = compute_collisions(tree_A, tree_B)

    entities_A = numpy.sort(numpy.unique([q[0] for q in entities]))
    entities_B = numpy.sort(numpy.unique([q[1] for q in entities]))

    cells_A = find_colliding_cells(mesh_A, tree_B.get_bbox(tree_B.num_bboxes - 1))
    cells_B = find_colliding_cells(mesh_B, tree_A.get_bbox(tree_A.num_bboxes - 1))

    assert numpy.allclose(entities_A, cells_A)
    assert numpy.allclose(entities_B, cells_B)


@pytest.mark.parametrize("dim", [0, 1])
def test_compute_closest_entity_1d(dim):
    ref_distance = 0.75
    N = 16
    points = numpy.array([[-ref_distance, 0, 0], [2 / N, 2 * ref_distance, 0]])
    mesh = UnitIntervalMesh(MPI.COMM_WORLD, N)
    tree = BoundingBoxTree(mesh, dim)
    num_entities_local = mesh.topology.index_map(dim).size_local + mesh.topology.index_map(dim).num_ghosts
    entities = numpy.arange(num_entities_local, dtype=numpy.int32)
    midpoint_tree = create_midpoint_tree(mesh, dim, entities)
    closest_entities = compute_closest_entity(tree, midpoint_tree, mesh, points)

    # Find which entity is colliding with known closest point on mesh
    p_c = numpy.array([[0, 0, 0], [2 / N, 0, 0]])
    colliding_entity_bboxes = compute_collisions(tree, p_c)

    # Refine search by checking for actual collision if the entities are
    # cells
    if dim == mesh.topology.dim:

        colliding_cells = compute_colliding_cells(mesh, colliding_entity_bboxes, p_c)
        for i in range(points.shape[0]):
            # If colliding entity is on process
            if len(colliding_cells.links(i)) > 0:
                assert numpy.isin(closest_entities[i], colliding_cells.links(i))
    else:
        for i in range(points.shape[0]):
            # Only check closest entity if any bounding box on the
            # process intersects with the point
            if colliding_entity_bboxes.links(i) > 0:
                assert numpy.isin(closest_entities[i], colliding_entity_bboxes.links(i))


@pytest.mark.parametrize("dim", [0, 1, 2])
def test_compute_closest_entity_2d(dim):
    points = numpy.array([-1.0, -0.01, 0.0])
    mesh = UnitSquareMesh(MPI.COMM_WORLD, 15, 15)
    tree = BoundingBoxTree(mesh, dim)
    num_entities_local = mesh.topology.index_map(dim).size_local + mesh.topology.index_map(dim).num_ghosts
    entities = numpy.arange(num_entities_local, dtype=numpy.int32)
    midpoint_tree = create_midpoint_tree(mesh, dim, entities)

    # Find which entity is colliding with known closest point on mesh
    closest_entities = compute_closest_entity(tree, midpoint_tree, mesh, points)

    # Find which entity is colliding with known closest point on mesh
    p_c = numpy.array([0, 0, 0])
    colliding_entity_bboxes = compute_collisions(tree, p_c)

    # Refine search by checking for actual collision if the entities are
    # cells
    if dim == mesh.topology.dim:
        colliding_cells = compute_colliding_cells(mesh, colliding_entity_bboxes, p_c)
        if len(colliding_cells) > 0:
            assert numpy.isin(closest_entities[0], colliding_cells)
    else:
        if len(colliding_entity_bboxes.links(0)) > 0:
            assert numpy.isin(closest_entities[0], colliding_entity_bboxes.links(0))


@pytest.mark.parametrize("dim", [1, 2, 3])
def test_compute_closest_entity_3d(dim):
    points = numpy.array([0.9, 0, 1.135])
    mesh = UnitCubeMesh(MPI.COMM_WORLD, 8, 8, 8)
    mesh.topology.create_entities(dim)

    tree = BoundingBoxTree(mesh, dim)
    num_entities_local = mesh.topology.index_map(dim).size_local + mesh.topology.index_map(dim).num_ghosts
    entities = numpy.arange(num_entities_local, dtype=numpy.int32)
    midpoint_tree = create_midpoint_tree(mesh, dim, entities)

    closest_entities = compute_closest_entity(tree, midpoint_tree, mesh, points)

    # Find which entity is colliding with known closest point on mesh
    p_c = numpy.array([0.9, 0, 1])
    colliding_entity_bboxes = compute_collisions(tree, p_c)

    # Refine search by checking for actual collision if the entities are
    # cells
    if dim == mesh.topology.dim:
        colliding_cells = compute_colliding_cells(mesh, colliding_entity_bboxes, p_c)
        if len(colliding_cells) > 0:
            assert numpy.isin(closest_entities[0], colliding_cells)
    else:
        if len(colliding_entity_bboxes.links(0)) > 0:
            assert numpy.isin(closest_entities[0], colliding_entity_bboxes.links(0))


@pytest.mark.parametrize("dim", [1, 2, 3])
def test_compute_closest_sub_entity(dim):
    """Compute distance from subset of cells in a mesh to a point inside the mesh"""
    ref_distance = 0.31
    points = numpy.array([0.5 + ref_distance, 0.5, 0.5])
    mesh = UnitCubeMesh(MPI.COMM_WORLD, 8, 8, 8)
    mesh.topology.create_entities(dim)

    left_entities = locate_entities(mesh, dim, lambda x: x[0] <= 0.5)
    tree = BoundingBoxTree(mesh, dim, left_entities)
    midpoint_tree = create_midpoint_tree(mesh, dim, left_entities)
    closest_entities = compute_closest_entity(tree, midpoint_tree, mesh, points)

    # Find which entity is colliding with known closest point on mesh
    p_c = numpy.array([0.5, 0.5, 0.5])
    colliding_entity_bboxes = compute_collisions(tree, p_c)

    # Refine search by checking for actual collision if the entities are
    # cells
    if dim == mesh.topology.dim:
        colliding_cells = compute_colliding_cells(mesh, colliding_entity_bboxes, p_c)
        if len(colliding_cells) > 0:
            assert numpy.isin(closest_entities[0], colliding_cells)
    else:
        if len(colliding_entity_bboxes.links(0)) > 0:
            assert numpy.isin(closest_entities[0], colliding_entity_bboxes.links(0))


def test_surface_bbtree():
    """Test creation of BBTree on subset of entities(surface cells)"""
    mesh = UnitCubeMesh(MPI.COMM_WORLD, 8, 8, 8)
    sf = cpp.mesh.exterior_facet_indices(mesh)
    tdim = mesh.topology.dim
    f_to_c = mesh.topology.connectivity(tdim - 1, tdim)
    cells = [f_to_c.links(f)[0] for f in sf]
    bbtree = BoundingBoxTree(mesh, tdim, cells)

    # test collision (should not collide with any)
    p = numpy.array([0.5, 0.5, 0.5])
    assert len(compute_collisions(bbtree, p).array) == 0


def test_sub_bbtree():
    """Testing point collision with a BoundingBoxTree of sub entitites"""
    mesh = UnitCubeMesh(MPI.COMM_WORLD, 4, 4, 4, cell_type=CellType.hexahedron)
    tdim = mesh.topology.dim
    fdim = tdim - 1

    def top_surface(x):
        return numpy.isclose(x[2], 1)

    top_facets = locate_entities_boundary(mesh, fdim, top_surface)
    f_to_c = mesh.topology.connectivity(tdim - 1, tdim)
    cells = [f_to_c.links(f)[0] for f in top_facets]
    bbtree = BoundingBoxTree(mesh, tdim, cells)

    # Compute a BBtree for all processes
    process_bbtree = bbtree.create_global_tree(mesh.mpi_comm())

    # Find possible ranks for this point
    point = numpy.array([0.2, 0.2, 1.0])
    ranks = compute_collisions(process_bbtree, point)

    # Compute local collisions
    cells = compute_collisions(bbtree, point)
    if MPI.COMM_WORLD.rank in ranks.array:
        assert len(cells.links(0)) > 0
    else:
        assert len(cells.links(0)) == 0


@pytest.mark.parametrize("ct", [CellType.hexahedron, CellType.tetrahedron])
@pytest.mark.parametrize("N", [7, 13])
def test_sub_bbtree_box(ct, N):
    """Test that the bounding box of the stem of the bounding box tree is what we expect"""
    mesh = UnitCubeMesh(MPI.COMM_WORLD, N, N, N, cell_type=ct)
    tdim = mesh.topology.dim
    fdim = tdim - 1

    def marker(x):
        return numpy.isclose(x[1], 1.0)

    facets = locate_entities_boundary(mesh, fdim, marker)
    f_to_c = mesh.topology.connectivity(fdim, tdim)
    cells = numpy.unique([f_to_c.links(f)[0] for f in facets])
    bbtree = BoundingBoxTree(mesh, tdim, cells)
    num_boxes = bbtree.num_bboxes
    if num_boxes > 0:
        bbox = bbtree.get_bbox(num_boxes - 1)
        assert numpy.isclose(bbox[0][1], (N - 1) / N)

    tree = BoundingBoxTree(mesh, tdim)
    assert num_boxes < tree.num_bboxes


@skip_in_parallel
def test_surface_bbtree_collision():
    """Compute collision between two meshes, where only one cell of each mesh are colliding"""
    tdim = 3
    mesh1 = UnitCubeMesh(MPI.COMM_WORLD, 3, 3, 3, CellType.hexahedron)
    mesh2 = UnitCubeMesh(MPI.COMM_WORLD, 3, 3, 3, CellType.hexahedron)
    mesh2.geometry.x[:, :] += numpy.array([0.9, 0.9, 0.9])

    sf = cpp.mesh.exterior_facet_indices(mesh1)
    f_to_c = mesh1.topology.connectivity(tdim - 1, tdim)

    # Compute unique set of cells (some will be counted multiple times)
    cells = list(set([f_to_c.links(f)[0] for f in sf]))
    bbtree1 = BoundingBoxTree(mesh1, tdim, cells)

    sf = cpp.mesh.exterior_facet_indices(mesh2)
    f_to_c = mesh2.topology.connectivity(tdim - 1, tdim)
    cells = list(set([f_to_c.links(f)[0] for f in sf]))
    bbtree2 = BoundingBoxTree(mesh2, tdim, cells)

    collisions = compute_collisions(bbtree1, bbtree2)
    assert len(collisions) == 1
