import bpy
import os
import json
import mathutils
import math
import sys
import time

"""
Single Case Tooth Rendering Script (Simplified & Robust)
- Sequence: Fixed to 4 (54 views)
- Type: Fixed to LIT only
- Target: Processes a single selected object folder
- Metadata: Includes Tone Mapping and HDR info
"""

class OT_SingleCaseRendering(bpy.types.Operator):
    bl_idname = "object.single_case_rendering"
    bl_label = "Single Case Rendering (LIT + Sequence 4)"
    bl_options = {"REGISTER", "UNDO"}

    folder_path: bpy.props.StringProperty(name="Select Object Folder", subtype="DIR_PATH")
    use_optimized_formats: bpy.props.BoolProperty(
        name="이미지 포맷 최적화 (WebP 사용)", 
        description="체크하면 WebP로, 해제하면 PNG로 저장합니다.", 
        default=True
    )

    def execute(self, context):
        if not self.folder_path or not os.path.isdir(self.folder_path):
            self.report({"ERROR"}, "Valid folder must be selected")
            return {"CANCELLED"}

        # === Setting up paths ===
        case_path = os.path.normpath(self.folder_path)
        case_name = os.path.basename(case_path)
        output_base = os.path.join(case_path, "output")
        lit_dir = os.path.join(output_base, "lit")
        os.makedirs(lit_dir, exist_ok=True)

        # === Scene Cleanup ===
        self._cleanup_scene()

        # === Render Engine Settings ===
        scene = bpy.context.scene
        scene.render.resolution_x = 512
        scene.render.resolution_y = 512
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'GPU'
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
        
        # Performance/Memory Optimization
        scene.cycles.tile_size = 256
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.max_bounces = 8

        # === Generate Camera Positions (Sequence 4) ===
        target = mathutils.Vector((0, 100, 0))
        distance = 100
        camera_positions = self._generate_sequence_4_positions(target, distance)

        # === Create Materials ===
        materials = self._create_lit_materials()

        # === Load Object and Setup ===
        obj_file, json_file = self._find_files(case_path)
        if not obj_file or not json_file:
            self.report({"ERROR"}, "OBJ or JSON file not found in the selected folder.")
            return {"CANCELLED"}

        obj = self._load_and_setup_mesh(obj_file, json_file, materials)
        
        # === Extract Metadata (Initial) ===
        metadata_path = os.path.join(output_base, f"metadata_{case_name}.json")
        self._save_metadata(scene, camera_positions, target, metadata_path)

        # === Rendering Loop ===
        print(f"Starting rendering for {case_name} (54 views)...")
        start_time = time.time()
        
        for idx, (view_name, cam_pos) in enumerate(camera_positions):
            # Create Camera
            cam_data = bpy.data.cameras.new(view_name + "_cam")
            cam_obj = bpy.data.objects.new(view_name + "_cam", cam_data)
            bpy.context.collection.objects.link(cam_obj)
            cam_obj.location = cam_pos
            direction = target - cam_pos
            cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            scene.camera = cam_obj
            cam_data.angle = math.radians(60)

            # Create Light (Sun following camera)
            light_data = bpy.data.lights.new(view_name + "_sun", type="SUN")
            light_data.energy = 5
            light_obj = bpy.data.objects.new(view_name + "_sun", light_data)
            bpy.context.collection.objects.link(light_obj)
            light_obj.parent = cam_obj

            # File format setup
            img_settings = scene.render.image_settings
            file_ext = ".webp" if self.use_optimized_formats else ".png"
            img_settings.file_format = "WEBP" if self.use_optimized_formats else "PNG"
            
            output_path = os.path.join(lit_dir, f"{case_name}_{view_name}{file_ext}")
            scene.render.filepath = output_path
            
            # Actual Render
            bpy.ops.render.render(write_still=True)

            # Cleanup Cam/Light for this view
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            bpy.data.objects.remove(light_obj, do_unlink=True)
            
            print(f"  [{idx+1}/54] Rendered {view_name}")

        self._cleanup_gpu_memory()
        total_time = time.time() - start_time
        print(f"Rendering complete in {total_time:.1f}s")
        
        self.report({"INFO"}, f"Rendering complete: {output_base}")
        if sys.platform == "win32":
            os.startfile(lit_dir)
        
        return {"FINISHED"}

    def _cleanup_scene(self):
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete()
        for block in [bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials]:
            for item in block:
                block.remove(item, do_unlink=True)

    def _generate_sequence_4_positions(self, target, distance):
        camera_positions = []
        base_vec = mathutils.Vector((0, -1, 0)) # Forward

        # Ring 1: +30 elevation (12 views)
        for i in range(12):
            rot_z = mathutils.Matrix.Rotation(math.radians(i * 30), 3, 'Z')
            rot_x = mathutils.Matrix.Rotation(math.radians(30), 3, 'X')
            pos = target + (rot_z @ rot_x @ base_vec).normalized() * distance
            camera_positions.append((f"ring1_{i+1:02d}", pos))

        # Ring 2: 0 elevation (18 views)
        for i in range(18):
            rot_z = mathutils.Matrix.Rotation(math.radians(i * 20), 3, 'Z')
            pos = target + (rot_z @ base_vec).normalized() * distance
            camera_positions.append((f"ring2_{i+1:02d}", pos))

        # Ring 3: -30 elevation (12 views)
        for i in range(12):
            rot_z = mathutils.Matrix.Rotation(math.radians(i * 30), 3, 'Z')
            rot_x = mathutils.Matrix.Rotation(math.radians(-30), 3, 'X')
            pos = target + (rot_z @ rot_x @ base_vec).normalized() * distance
            camera_positions.append((f"ring3_{i+1:02d}", pos))

        # Ring 4: Front sweep (10 views)
        for i in range(10):
            elev = 60 - i * 12
            rot_x = mathutils.Matrix.Rotation(math.radians(elev), 3, 'X')
            pos = target + (rot_x @ base_vec).normalized() * distance
            camera_positions.append((f"ring4_{i+1:02d}", pos))

        # Ring 5: Poles (2 views)
        for elev in [90, -90]:
            rot_x = mathutils.Matrix.Rotation(math.radians(elev), 3, 'X')
            rot_z = mathutils.Matrix.Rotation(math.radians(90), 3, 'Z')
            pos = target + (rot_z @ rot_x @ base_vec).normalized() * distance
            camera_positions.append((f"ring5_{1 if elev > 0 else 2:02d}", pos))

        return camera_positions

    def _create_lit_materials(self):
        mats = {}
        
        def setup_principled(mat, color, roughness):
            nodes = mat.node_tree.nodes
            bsdf = nodes.get("Principled BSDF") or nodes.new("ShaderNodeBsdfPrincipled")
            
            # Base Color 설정
            try:
                bsdf.inputs["Base Color"].default_value = color
            except KeyError:
                bsdf.inputs[0].default_value = color
                
            # Roughness 설정
            try:
                bsdf.inputs["Roughness"].default_value = roughness
            except KeyError:
                # 버전에 따라 7 또는 9일 수 있음
                try: bsdf.inputs[7].default_value = roughness
                except: bsdf.inputs[9].default_value = roughness
            
            # Coat 설정 (블렌더 4.0 이상)
            try:
                if "Coat Weight" in bsdf.inputs:
                    bsdf.inputs["Coat Weight"].default_value = 0.8
            except:
                pass
            
            return mat

        # Gum Material
        g_mat = bpy.data.materials.new("Gingiva_lit")
        g_mat.use_nodes = True
        mats['gum'] = setup_principled(g_mat, (1.0, 0.196, 0.282, 1.0), 0.2)

        # Tooth Material
        t_mat = bpy.data.materials.new("Teeth_lit")
        t_mat.use_nodes = True
        mats['tooth'] = setup_principled(t_mat, (1.0, 1.0, 1.0, 1.0), 0.1)
        
        return mats

    def _find_files(self, path):
        obj, jsn = None, None
        for f in os.listdir(path):
            if f.endswith(".obj"): obj = os.path.join(path, f)
            if f.endswith(".json") and not f.startswith("metadata"): jsn = os.path.join(path, f)
        return obj, jsn

    def _load_and_setup_mesh(self, obj_file, json_file, materials):
        bpy.ops.wm.obj_import(filepath=obj_file)
        obj = bpy.context.selected_objects[0]
        mesh = obj.data
        
        # Apply transformation (consistent with optimized.py)
        obj.rotation_euler.x += math.radians(-45)
        obj.location += mathutils.Vector((0, 29.29, 70))
        
        mesh.materials.clear()
        mesh.materials.append(materials['gum'])
        mesh.materials.append(materials['tooth'])

        with open(json_file) as f:
            meta = json.load(f)
        labels = meta["labels"]
        
        for poly in mesh.polygons:
            face_labels = [labels[v] for v in poly.vertices if v < len(labels)]
            poly.material_index = 1 if all(l > 0 for l in face_labels) else 0
        return obj

    def _save_metadata(self, scene, camera_positions, target, path):
        views = []
        res_x = scene.render.resolution_x
        res_y = scene.render.resolution_y
        
        for name, pos in camera_positions:
            # Temporary cam for calculation
            cam_data = bpy.data.cameras.new("temp")
            cam_obj = bpy.data.objects.new("temp", cam_data)
            bpy.context.collection.objects.link(cam_obj)
            cam_obj.location = pos
            cam_obj.rotation_euler = (target - pos).to_track_quat("-Z", "Y").to_euler()
            cam_data.angle = math.radians(60)
            bpy.context.view_layer.update()
            
            # Intrinsics
            f = (res_y / 2.0) / math.tan(cam_data.angle / 2.0)
            K = [[f, 0, res_x/2], [0, f, res_y/2], [0, 0, 1]]
            
            views.append({
                'view_name': name,
                'location': list(cam_obj.location),
                'rotation_euler': list(cam_obj.rotation_euler),
                'intrinsic_K': K,
                'extrinsic_matrix': [list(row) for row in cam_obj.matrix_world.inverted()]
            })
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            bpy.data.cameras.remove(cam_data, do_unlink=True)

        metadata = {
            'info': {
                'case_name': os.path.basename(os.path.dirname(path)),
                'sequence': 4,
                'render_type': 'LIT',
                'resolution': [res_x, res_y],
                'tone_mapping': {
                    'view_transform': scene.view_settings.view_transform,
                    'look': scene.view_settings.look,
                    'exposure': scene.view_settings.exposure,
                    'gamma': scene.view_settings.gamma
                },
                'is_hdr': False # LIT is SDR
            },
            'views': views
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

    def _cleanup_gpu_memory(self):
        import gc
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        gc.collect()

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

def menu_func(self, context):
    self.layout.operator(OT_SingleCaseRendering.bl_idname)

def register():
    bpy.utils.register_class(OT_SingleCaseRendering)
    bpy.types.TOPBAR_MT_file.append(menu_func)

def unregister():
    bpy.utils.unregister_class(OT_SingleCaseRendering)
    bpy.types.TOPBAR_MT_file.remove(menu_func)

if __name__ == "__main__":
    register()
