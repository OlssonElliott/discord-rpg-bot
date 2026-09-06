"""Blender-side scene builder and PNG renderer for neutral polyhedral dice.

This script is launched by ``generate_d20_assets.py``. It requires Blender's
``bpy`` module and is not intended to run with the bot's Python interpreter.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

import bpy
from itertools import combinations, product

from mathutils import Matrix, Quaternion, Vector


DIE_RADIUS = 1.5
FINAL_HEIGHT = 0.08
FINAL_HOLD_SECONDS = 0.9


def blender_arguments() -> list[str]:
    try:
        separator = sys.argv.index("--")
    except ValueError:
        return []
    return sys.argv[separator + 1 :]


def parse_results(value: str) -> list[int]:
    results = sorted({int(part) for part in value.split(",") if part})
    if not results or min(results) < 1:
        raise argparse.ArgumentTypeError("Results must be positive integers.")
    return results


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfDiffuse")
    shader.inputs["Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def look_at(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def configure_scene(
    resolution: int,
    fps: int,
    duration: float,
    samples: int,
) -> tuple[bpy.types.Scene, bpy.types.Object]:
    if bpy.app.version < (4, 2, 0):
        raise RuntimeError("This generator requires Blender 4.2 or newer.")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.materials):
        bpy.data.materials.remove(block)

    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    else:
        raise RuntimeError("A compatible Blender Eevee render engine was not found.")

    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 80
    scene.frame_start = 1
    scene.frame_end = max(2, round(fps * duration))
    scene.render.use_file_extension = True
    scene.render.use_overwrite = True
    scene.render.use_placeholder = False
    scene.render.dither_intensity = 0
    scene.render.filter_size = 0.8
    scene.view_settings.view_transform = "Standard"
    try:
        scene.view_settings.look = "Medium High Contrast"
    except TypeError:
        pass
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1

    if hasattr(scene, "eevee"):
        for sample_property in ("taa_render_samples", "taa_samples"):
            if hasattr(scene.eevee, sample_property):
                setattr(scene.eevee, sample_property, samples)
                break

    scene.world.color = (0.025, 0.025, 0.025)

    bpy.ops.object.camera_add(location=(0.0, -6.7, 3.0))
    camera = bpy.context.object
    camera.name = "D20 Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 3.95
    camera.data.lens = 55
    look_at(camera, Vector((0.0, 0.0, 0.22)))
    scene.camera = camera

    add_area_light("Key", (-3.8, -4.5, 6.2), 1050, 2.8)
    add_area_light("Fill", (4.2, -2.0, 2.7), 325, 4.0)
    add_area_light("Rim", (0.5, 3.8, 4.5), 650, 2.4)
    return scene, camera


def add_area_light(
    name: str,
    location: tuple[float, float, float],
    energy: float,
    size: float,
) -> bpy.types.Object:
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    look_at(light, Vector((0.0, 0.0, 0.0)))
    return light


def face_sort_key(face: dict[str, object]) -> tuple[float, float, float]:
    normal = face["normal"]
    return tuple(round(component, 6) for component in (normal.z, normal.y, normal.x))


def polygon_normal(vertices: list[Vector], face: list[int]) -> Vector:
    normal = Vector((0.0, 0.0, 0.0))
    for index, vertex_index in enumerate(face):
        current = vertices[vertex_index]
        following = vertices[face[(index + 1) % len(face)]]
        normal.x += (current.y - following.y) * (current.z + following.z)
        normal.y += (current.z - following.z) * (current.x + following.x)
        normal.z += (current.x - following.x) * (current.y + following.y)
    return normal.normalized()


def convex_faces(vertices: list[Vector]) -> list[list[int]]:
    """Find the polygon faces of a small centered convex point set."""
    face_sets: set[frozenset[int]] = set()
    tolerance = 1e-5
    for first, second, third in combinations(range(len(vertices)), 3):
        normal = (vertices[second] - vertices[first]).cross(
            vertices[third] - vertices[first]
        )
        if normal.length < tolerance:
            continue
        normal.normalize()
        distances = [normal.dot(vertex - vertices[first]) for vertex in vertices]
        if max(distances) > tolerance and min(distances) < -tolerance:
            continue
        coplanar = frozenset(
            index for index, distance in enumerate(distances) if abs(distance) <= tolerance
        )
        if len(coplanar) >= 3:
            face_sets.add(coplanar)

    faces: list[list[int]] = []
    for face_set in face_sets:
        center = sum((vertices[index] for index in face_set), Vector()) / len(face_set)
        outward = center.normalized()
        first_index = min(face_set)
        horizontal = (vertices[first_index] - center).normalized()
        vertical = outward.cross(horizontal).normalized()
        ordered = sorted(
            face_set,
            key=lambda index: math.atan2(
                (vertices[index] - center).dot(vertical),
                (vertices[index] - center).dot(horizontal),
            ),
        )
        if polygon_normal(vertices, ordered).dot(outward) < 0:
            ordered.reverse()
        faces.append(ordered)
    return faces


def die_vertices(sides: int) -> list[Vector]:
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    if sides == 4:
        vertices = [
            Vector((1, 1, 1)),
            Vector((-1, -1, 1)),
            Vector((-1, 1, -1)),
            Vector((1, -1, -1)),
        ]
    elif sides == 6:
        vertices = [Vector(values) for values in product((-1.0, 1.0), repeat=3)]
    elif sides == 8:
        vertices = [
            Vector((sign if axis == 0 else 0, sign if axis == 1 else 0, sign if axis == 2 else 0))
            for axis in range(3)
            for sign in (-1.0, 1.0)
        ]
    elif sides == 10:
        antiprism = []
        for index in range(5):
            angle = index * math.tau / 5
            antiprism.append(Vector((math.cos(angle), math.sin(angle), 0.5)))
            angle += math.pi / 5
            antiprism.append(Vector((math.cos(angle), math.sin(angle), -0.5)))
        vertices = []
        for face in convex_faces(antiprism):
            center = sum((antiprism[index] for index in face), Vector()) / len(face)
            normal = polygon_normal(antiprism, face)
            distance = normal.dot(center)
            vertices.append(normal / distance)
    elif sides == 12:
        vertices = [Vector(values) for values in product((-1.0, 1.0), repeat=3)]
        for first, second in product((-1.0, 1.0), repeat=2):
            vertices.extend(
                (
                    Vector((0.0, first / phi, second * phi)),
                    Vector((first / phi, second * phi, 0.0)),
                    Vector((first * phi, 0.0, second / phi)),
                )
            )
    elif sides == 20:
        vertices = []
        for first, second in product((-1.0, 1.0), repeat=2):
            vertices.extend(
                (
                    Vector((0.0, first, second * phi)),
                    Vector((first, second * phi, 0.0)),
                    Vector((first * phi, 0.0, second)),
                )
            )
    else:
        raise ValueError(f"Unsupported visual die: d{sides}")

    scale = DIE_RADIUS / max(vertex.length for vertex in vertices)
    return [vertex * scale for vertex in vertices]


def assign_balanced_numbers(
    mesh: bpy.types.Mesh, sides: int
) -> dict[int, dict[str, object]]:
    """Assign every face once, with opposing pairs summing to sides + 1."""
    faces: dict[int, dict[str, object]] = {}
    for polygon in mesh.polygons:
        center = polygon.center.copy()
        normal = polygon.normal.copy().normalized()
        first_vertex = mesh.vertices[polygon.vertices[0]].co
        up = (first_vertex - center).normalized()
        if sides == 4:
            # Spin a tetrahedron around a real vertex-to-opposite-face symmetry
            # axis. Using an arbitrary axis within the presented face makes its
            # apex sweep sideways and reads as a wobble rather than a clean turn.
            polygon = mesh.polygons[polygon.index]
            stable_spin_axis = mesh.vertices[polygon.vertices[0]].co.normalized()
            projected_axis = (
                stable_spin_axis
                - normal * stable_spin_axis.dot(normal)
            )
        elif sides == 6:
            # Keep the presented square face upright rather than balancing it
            # on a corner while leaving the printed number upright.
            reference_axis = (
                Vector((0.0, 0.0, 1.0))
                if abs(normal.z) < 0.9
                else Vector((0.0, 1.0, 0.0))
            )
            projected_axis = reference_axis - normal * reference_axis.dot(normal)
            stable_spin_axis = projected_axis.normalized()
        elif sides == 10:
            # A conventional d10 is visibly elongated between its two poles.
            # Keep that axis vertical at rest instead of presenting the kite
            # sideways, which makes the die look flattened.
            pole_axis = Vector((0.0, 0.0, 1.0))
            projected_axis = pole_axis - normal * pole_axis.dot(normal)
            stable_spin_axis = projected_axis.normalized()
        else:
            candidate_axes = [
                vertex.co.copy().normalized() for vertex in mesh.vertices
            ]

            def axis_score(axis: Vector) -> tuple[float, float]:
                normal_alignment = abs(axis.dot(normal))
                projected = axis - normal * axis.dot(normal)
                up_alignment = abs(projected.normalized().dot(up))
                return round(normal_alignment, 5), -up_alignment

            spin_axis = min(candidate_axes, key=axis_score)
            projected_axis = spin_axis - normal * spin_axis.dot(normal)
            if projected_axis.dot(up) < 0:
                projected_axis.negate()
            stable_spin_axis = projected_axis.normalized()
        faces[polygon.index] = {
            "index": polygon.index,
            "center": center,
            "normal": normal,
            "up": projected_axis.normalized(),
            "spin_axis": stable_spin_axis,
        }

    if len(faces) != sides:
        raise RuntimeError(f"Expected {sides} d{sides} faces, found {len(faces)}.")

    remaining = set(faces)
    numbered: dict[int, dict[str, object]] = {}
    for low_number in range(1, sides // 2 + 1):
        current_index = min(remaining, key=lambda index: face_sort_key(faces[index]))
        remaining.remove(current_index)
        current_normal = faces[current_index]["normal"]
        opposite_index = min(
            remaining,
            key=lambda index: current_normal.dot(faces[index]["normal"]),
        )
        remaining.remove(opposite_index)
        numbered[low_number] = faces[current_index]
        numbered[sides + 1 - low_number] = faces[opposite_index]
    return numbered


def orientation_from_axes(normal: Vector, up: Vector) -> Quaternion:
    right = up.cross(normal).normalized()
    return Matrix((right, up, normal)).transposed().to_quaternion()


def build_die(
    sides: int,
) -> tuple[bpy.types.Object, dict[int, dict[str, object]]]:
    face_materials = tuple(
        make_material(
            f"Matte neutral faces {index + 1}",
            (luminance, luminance, luminance, 1.0),
            0.9,
        )
        for index, luminance in enumerate((0.38, 0.48, 0.58))
    )
    edge_material = make_material(
        "Edge mask marker", (0.015, 0.60, 0.015, 1.0), 1.0
    )
    number_material = make_material(
        "Number mask marker", (0.015, 0.015, 0.60, 1.0), 1.0
    )

    root = bpy.data.objects.new(f"Animated D{sides}", None)
    bpy.context.collection.objects.link(root)
    root.rotation_mode = "QUATERNION"

    vertices = die_vertices(sides)
    faces = convex_faces(vertices)
    mesh = bpy.data.meshes.new(f"Neutral D{sides} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    die = bpy.data.objects.new(f"Neutral D{sides}", mesh)
    bpy.context.collection.objects.link(die)
    for face_material in face_materials:
        die.data.materials.append(face_material)
    die.data.materials.append(edge_material)
    die.parent = root
    for polygon in die.data.polygons:
        polygon.use_smooth = False
        polygon.material_index = polygon.index % len(face_materials)

    shortest_edge = min(
        (mesh.vertices[edge.vertices[0]].co - mesh.vertices[edge.vertices[1]].co).length
        for edge in mesh.edges
    )
    bevel = die.modifiers.new(f"Soft d{sides} edges", "BEVEL")
    bevel.width = min(0.14, shortest_edge * 0.11)
    bevel.segments = 2
    bevel.limit_method = "ANGLE"
    bevel.material = len(face_materials)

    die.data.update()
    numbered_faces = assign_balanced_numbers(die.data, sides)
    for number, face in numbered_faces.items():
        bpy.ops.object.text_add()
        label = bpy.context.object
        label.name = f"Face {number:02d}"
        label.data.body = str(number)
        label.data.align_x = "CENTER"
        label.data.align_y = "CENTER"
        polygon = die.data.polygons[face["index"]]
        face_vertices = [die.data.vertices[index].co for index in polygon.vertices]
        center = face["center"]
        inset = min(
            (first - center).cross(second - center).length / (second - first).length
            for first, second in zip(face_vertices, face_vertices[1:] + face_vertices[:1])
        )
        double_digit_scale = 0.80 if sides == 10 else 0.68
        label.data.size = min(
            0.68, inset * (0.88 if number < 10 else double_digit_scale)
        )
        label.data.offset = 0.012
        label.data.extrude = 0.009
        label.data.bevel_depth = 0.0015
        label.data.bevel_resolution = 1
        label.data.materials.append(number_material)
        label.location = face["center"] + face["normal"] * 0.026
        label.rotation_mode = "QUATERNION"
        label.rotation_quaternion = orientation_from_axes(face["normal"], face["up"])
        label.parent = root

    return root, numbered_faces


def final_face_orientation(
    face: dict[str, object], camera: bpy.types.Object
) -> Quaternion:
    local_normal = face["normal"]
    local_spin_axis = face["spin_axis"]
    local_forward = (
        local_normal - local_spin_axis * local_normal.dot(local_spin_axis)
    ).normalized()
    local_right = local_spin_axis.cross(local_forward).normalized()
    local_basis = Matrix(
        (local_right, local_spin_axis, local_forward)
    ).transposed()

    camera_rotation = camera.rotation_euler.to_quaternion()
    target_normal = (camera.location - Vector((0.0, 0.0, FINAL_HEIGHT))).normalized()
    camera_up = camera_rotation @ Vector((0.0, 1.0, 0.0))
    target_up = (camera_up - target_normal * camera_up.dot(target_normal)).normalized()
    target_right = target_up.cross(target_normal).normalized()
    target_basis = Matrix((target_right, target_up, target_normal)).transposed()
    orientation = (target_basis @ local_basis.inverted()).to_quaternion()

    if (orientation @ local_spin_axis).dot(target_up) < 0.999:
        raise RuntimeError("Could not align the die's stable spin axis.")
    expected_forward_alignment = math.sqrt(
        max(0.0, 1.0 - local_normal.dot(local_spin_axis) ** 2)
    )
    if (orientation @ local_normal).dot(target_normal) < expected_forward_alignment - 0.01:
        raise RuntimeError("Could not orient the requested die face toward the camera.")
    return orientation


def pose_result(
    root: bpy.types.Object,
    final_orientation: Quaternion,
    spin_axis: Vector,
    turns: float,
) -> None:
    root.animation_data_clear()
    root.rotation_quaternion = (
        Quaternion(spin_axis, turns * math.tau) @ final_orientation
    )
    root.location = (0.0, 0.0, FINAL_HEIGHT)


def horizontal_spin_turns(
    frame_number: int, frame_count: int, fps: int
) -> float:
    """Spin quickly to the right, ease out, then hold the final orientation."""
    settle_end = settle_frame_number(frame_count, fps)
    if frame_number >= settle_end:
        return 0.0

    progress = (frame_number - 1) / (settle_end - 1)
    return -1.5 * ((1.0 - progress) ** 2)


def settle_frame_number(frame_count: int, fps: int) -> int:
    """Return the one final frame that the GIF encoder extends into a hold."""
    hold_frames = min(round(FINAL_HOLD_SECONDS * fps), frame_count - 2)
    return frame_count - hold_frames + 1


def render_results(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    root: bpy.types.Object,
    numbered_faces: dict[int, dict[str, object]],
    sides: int,
    results: list[int],
    output_directory: Path,
) -> None:
    for result in results:
        print(f"Rendering horizontally spinning neutral d{sides} result {result}...")
        result_directory = output_directory / f"d{sides}_{result}"
        result_directory.mkdir(parents=True, exist_ok=True)
        for old_frame in result_directory.glob("frame_*.png"):
            old_frame.unlink()

        orientation = final_face_orientation(numbered_faces[result], camera)
        spin_axis = (
            camera.rotation_euler.to_quaternion() @ Vector((0.0, 1.0, 0.0))
        ).normalized()
        frame_count = scene.frame_end - scene.frame_start + 1
        final_rendered_frame = settle_frame_number(frame_count, scene.render.fps)
        for frame_number in range(scene.frame_start, final_rendered_frame + 1):
            pose_result(
                root,
                orientation,
                spin_axis,
                horizontal_spin_turns(frame_number, frame_count, scene.render.fps),
            )
            scene.frame_set(frame_number)
            scene.render.filepath = str(
                result_directory / f"frame_{frame_number:04d}.png"
            )
            bpy.ops.render.render(write_still=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sides", type=int, choices=(4, 6, 8, 10, 12, 20), default=20)
    parser.add_argument("--results", type=parse_results, required=True)
    parser.add_argument("--resolution", type=int, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--samples", type=int, required=True)
    args = parser.parse_args(blender_arguments())
    if max(args.results) > args.sides:
        parser.error(f"Results for d{args.sides} must be between 1 and {args.sides}.")

    scene, camera = configure_scene(
        args.resolution, args.fps, args.duration, args.samples
    )
    root, numbered_faces = build_die(args.sides)
    render_results(
        scene,
        camera,
        root,
        numbered_faces,
        args.sides,
        args.results,
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
