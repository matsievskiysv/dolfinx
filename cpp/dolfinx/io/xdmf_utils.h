// Copyright (C) 2012 Chris N. Richardson
//
// This file is part of DOLFINx (https://www.fenicsproject.org)
//
// SPDX-License-Identifier:    LGPL-3.0-or-later

#pragma once

#include "HDF5Interface.h"
#include "pugixml.hpp"
#include "utils.h"
#include <array>
#include <dolfinx/common/utils.h>
#include <dolfinx/mesh/cell_types.h>
#include <string>
#include <utility>
#include <vector>
#include <xtl/xspan.hpp>

namespace pugi
{
class xml_node;
} // namespace pugi

namespace dolfinx
{

namespace fem
{
template <typename T>
class Function;
} // namespace fem

namespace fem
{
class CoordinateElement;
}

namespace mesh
{
class Mesh;
}

namespace io::xdmf_utils
{

// Get DOLFINx cell type string from XML topology node
// @return DOLFINx cell type and polynomial degree
std::pair<std::string, int> get_cell_type(const pugi::xml_node& topology_node);

// Return (0) HDF5 filename and (1) path in HDF5 file from a DataItem
// node
std::array<std::string, 2> get_hdf5_paths(const pugi::xml_node& dataitem_node);

std::string get_hdf5_filename(std::string xdmf_filename);

/// Get dimensions from an XML DataSet node
std::vector<std::int64_t> get_dataset_shape(const pugi::xml_node& dataset_node);

/// Get number of cells from an XML Topology node
std::int64_t get_num_cells(const pugi::xml_node& topology_node);

/// Get point data values for linear or quadratic mesh into flattened 2D
/// array
std::vector<double> get_point_data_values(const fem::Function<double>& u);
std::vector<std::complex<double>>
get_point_data_values(const fem::Function<std::complex<double>>& u);

/// Get cell data values as a flattened 2D array
std::vector<double> get_cell_data_values(const fem::Function<double>& u);
std::vector<std::complex<double>>
get_cell_data_values(const fem::Function<std::complex<double>>& u);

/// Get the VTK string identifier
std::string vtk_cell_type_str(mesh::CellType cell_type, int num_nodes);

/// Get owned entities and associated data from input entities defined
/// by global 'node' indices. The input entities and data can be
/// supplied on any rank and this function will manage the
/// communication.
///
/// @param[in] mesh A mesh
/// @param[in] entity_dim Topological dimension of entities to extract
/// @param[in] entities Mesh entities defined using global input indices
/// ('nodes'), typically from an input mesh file, e.g. [gi0, gi1, gi2]
/// for a triangle. Let [v0, v1, v2] be the vertex indices of some
/// triangle (using local indexing). Each vertex has a 'node' (geometry
/// dof) index, and each node has a persistent input global index, so
/// the triangle [gi0, gi1, gi2] could be identified with [v0, v1, v2].
/// @param[in] data Data associated with each entity in `entities`.
/// @return (Cell-vertex connectivity of owned entities, associated
/// data (values) with each entity)
/// @note This function involves parallel distribution and must be
/// called collectively. Global input indices for entities which are not
/// owned by current rank could passed to this function. E.g., rank0
/// provides an entity with global input indices [gi0, gi1, gi2], but
/// this identifies a triangle that is owned by rank1. It will be
/// distributed and rank1 will receive (local) cell-vertex connectivity
/// for this triangle.
std::pair<xt::xtensor<std::int32_t, 2>, std::vector<std::int32_t>>
distribute_entity_data(const mesh::Mesh& mesh, int entity_dim,
                       const xt::xtensor<std::int64_t, 2>& entities,
                       const xtl::span<const std::int32_t>& data);

/// TODO: Document
template <typename T>
void add_data_item(pugi::xml_node& xml_node, const hid_t h5_id,
                   const std::string h5_path, const T& x,
                   const std::int64_t offset,
                   const std::vector<std::int64_t> shape,
                   const std::string number_type, const bool use_mpi_io)
{
  // Add DataItem node
  assert(xml_node);
  pugi::xml_node data_item_node = xml_node.append_child("DataItem");
  assert(data_item_node);

  // Add dimensions attribute
  std::string dims;
  for (auto d : shape)
    dims += std::to_string(d) + std::string(" ");
  dims.pop_back();
  data_item_node.append_attribute("Dimensions") = dims.c_str();

  // Set type for topology data (needed by XDMF to prevent default to
  // float)
  if (!number_type.empty())
    data_item_node.append_attribute("NumberType") = number_type.c_str();

  // Add format attribute
  if (h5_id < 0)
  {
    data_item_node.append_attribute("Format") = "XML";
    assert(shape.size() == 2);
    data_item_node.append_child(pugi::node_pcdata)
        .set_value(common::container_to_string(x, 16, shape[1]).c_str());
  }
  else
  {
    data_item_node.append_attribute("Format") = "HDF";

    // Get name of HDF5 file, including path
    const std::string hdf5_filename = HDF5Interface::get_filename(h5_id);
    const std::string filename = dolfinx::io::get_filename(hdf5_filename);

    // Add HDF5 filename and HDF5 internal path to XML file
    const std::string xdmf_path = filename + std::string(":") + h5_path;
    data_item_node.append_child(pugi::node_pcdata).set_value(xdmf_path.c_str());

    // Compute data offset and range of values
    std::int64_t local_shape0 = x.size();
    for (std::size_t i = 1; i < shape.size(); ++i)
    {
      assert(local_shape0 % shape[i] == 0);
      local_shape0 /= shape[i];
    }

    const std::array local_range{offset, offset + local_shape0};
    HDF5Interface::write_dataset(h5_id, h5_path, x.data(), local_range, shape,
                                 use_mpi_io, false);

    // Add partitioning attribute to dataset
    // std::vector<std::size_t> partitions;
    // std::vector<std::size_t> offset_tmp(1, offset);
    // dolfinx::MPI::gather(comm, offset_tmp, partitions);
    // dolfinx::MPI::broadcast(comm, partitions);
    // HDF5Interface::add_attribute(h5_id, h5_path, "partition", partitions);
  }
}

} // namespace io::xdmf_utils
} // namespace dolfinx
