import bpy
import os
import json
import mathutils
import math
import subprocess
import sys
import time


# 설정 변수
MAX_CASES = 50  # 처리할 최대 케이스 수
START_CASE = 45  # 시작 케이스 번호 (1부터 시작)
Reverses = False  # 폴더 순서 역순 여부
Sequence = True # true : 카메라 각도를 연속으로, false : 기존 10개 카메라 각도 사용용 
# top -> left -> bottom 3개의 기존 카메라 각도를 키프레임으로 사용
# top -> left 15장, left -> bottom 15장, 총 30장의 이미지를 저장함.
# 전체 사진들을 순서대로 이어서 보면 동영상처럼 카메라가 orbital 회전하는것처럼 구현해야함

# 렌더링 타입별 활성화 설정
RENDER_LIT = True  # 라이팅 머티리얼 (Cycles)
RENDER_UNLIT = False  # semantic map (EEVEE)
RENDER_MATT = False  # 매트 머티리얼 (EEVEE)
RENDER_DEPTH = False  # 뎁스 맵 (EEVEE)
RENDER_NORMAL = False  # 노멀 맵 (EEVEE)
RENDER_CURVATURE = False  # 곡률 맵 (Cycles)

# Windows에서 별도 콘솔창 띄우기
if sys.platform == "win32":
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # 콘솔 할당
        kernel32.AllocConsole()

        # 콘솔 창 제목 설정
        kernel32.SetConsoleTitleW("Blender Tooth Rendering Progress - Optimized")

        # 콘솔 창 크기 조정
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.SetWindowPos(hwnd, 0, 100, 100, 800, 600, 0x0040)
    except:
        pass


class OT_SelectFolderAndColorize(bpy.types.Operator):
    bl_idname = "object.select_folder_and_colorize"
    bl_label = "Select Folder and Apply Gingiva/Tooth Materials (Optimized)"
    bl_options = {"REGISTER", "UNDO"}

    folder_path: bpy.props.StringProperty(name="folder", subtype="DIR_PATH")

    def execute(self, context):

        # === 씬 정리 ===
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        for block in bpy.data.meshes:
            bpy.data.meshes.remove(block, do_unlink=True)
        for block in bpy.data.lights:
            bpy.data.lights.remove(block, do_unlink=True)
        for block in bpy.data.cameras:
            bpy.data.cameras.remove(block, do_unlink=True)
        # Operator 실행 맨 처음(한 번만)
        for block in bpy.data.materials:
            bpy.data.materials.remove(block, do_unlink=True)

        # === 저장 경로 및 파일명 설정 ===
        # 선택한 폴더(self.folder_path)의 상위 폴더 안에 output 폴더 생성
        selected_root = os.path.normpath(self.folder_path)
        selected_parent = os.path.dirname(selected_root)
        if not selected_parent or selected_parent == selected_root:
            selected_parent = selected_root
        output_base = os.path.join(selected_parent, "output")
        lit_dir = os.path.join(output_base, "lit")
        unlit_dir = os.path.join(output_base, "unlit")
        matt_dir = os.path.join(output_base, "matt")
        depth_dir = os.path.join(output_base, "depth")
        normal_dir = os.path.join(output_base, "normal")
        curvature_dir = os.path.join(output_base, "curvature")
        os.makedirs(lit_dir, exist_ok=True)
        os.makedirs(unlit_dir, exist_ok=True)
        os.makedirs(matt_dir, exist_ok=True)
        os.makedirs(depth_dir, exist_ok=True)
        os.makedirs(normal_dir, exist_ok=True)
        os.makedirs(curvature_dir, exist_ok=True)

        # === 렌더 엔진 및 해상도 설정 ===
        scene = bpy.context.scene
        scene.render.resolution_x = 512
        scene.render.resolution_y = 512
        scene.render.resolution_percentage = 100

        # GPU 렌더링 설정 (Cycles) - 메모리 누수 방지
        scene.cycles.device = "GPU"
        scene.cycles.samples = 64  # 샘플 수 감소로 GPU 부하 완화
        scene.cycles.use_denoising = True

        # GPU 메모리 최적화 (메모리 누수 방지)
        scene.cycles.tile_size = 256  # 타일 크기 감소로 메모리 사용량 최적화
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.01
        scene.cycles.adaptive_min_samples = 32  # 최소 샘플 수 감소
        scene.cycles.max_bounces = 8  # 반사 횟수 감소로 GPU 부하 완화
        scene.cycles.caustics_reflective = False  # 카우스틱 비활성화로 메모리 절약
        scene.cycles.caustics_refractive = False  # 카우스틱 비활성화로 메모리 절약

        # === 카메라 포즈 정의 ===
        target = mathutils.Vector((0, 100, 0))
        distance = 100
        
        if Sequence:
            # Sequence 모드: top -> left -> bottom 3개 키포인트만 사용
            sequence_keypoints = [
                ("top", mathutils.Vector((0, -1, 1))),
                ("left", mathutils.Vector((-1, -1, 0))),
                ("bottom", mathutils.Vector((0, -1, -1))),
            ]
            camera_positions = []
            for name, view_dir in sequence_keypoints:
                view_dir = view_dir.normalized()
                cam_pos = target + view_dir * distance
                camera_positions.append((name, cam_pos))
        else:
            # 기존 모드: 10개 카메라 각도 사용
            camera_configs = [
                ("front", mathutils.Vector((0, -1, 0))),
                ("top", mathutils.Vector((0, -1, 1))),
                ("bottom", mathutils.Vector((0, -1, -1))),
                ("right", mathutils.Vector((1, -1, 0))),
                ("left", mathutils.Vector((-1, -1, 0))),
                ("front_top_right", mathutils.Vector((1, -1, 1))),
                ("front_top_left", mathutils.Vector((-1, -1, 1))),
                ("front_bottom_right", mathutils.Vector((1, -1, -1))),
                ("front_bottom_left", mathutils.Vector((-1, -1, -1))),
                ("front_slightly_up", mathutils.Vector((0, -1, 0.5))),
            ]
            camera_positions = []
            for name, view_dir in camera_configs:
                view_dir = view_dir.normalized()
                cam_pos = target + view_dir * distance
                camera_positions.append((name, cam_pos))

        # === 머티리얼 생성 ===
        materials = self._create_materials()

        # === 하위 폴더(케이스) 자동 순회 ===
        parent_folder = os.path.basename(os.path.normpath(self.folder_path))
        all_case_folders = [
            f
            for f in sorted(os.listdir(self.folder_path), reverse=Reverses)
            if os.path.isdir(os.path.join(self.folder_path, f))
        ]
        
        # 시작 케이스부터 최대 케이스까지 선택
        start_idx = START_CASE - 1  # 0-based 인덱스로 변환
        end_idx = min(MAX_CASES, len(all_case_folders))
        case_folders = all_case_folders[start_idx:end_idx]

        total = len(case_folders)
        total_all = len(all_case_folders)
        
        # 활성화된 렌더링 타입 수 계산
        active_render_types = sum([
            RENDER_LIT, RENDER_UNLIT, RENDER_MATT, 
            RENDER_DEPTH, RENDER_NORMAL, RENDER_CURVATURE
        ])

        start_time = time.time()
        print(f"=== OPTIMIZED RENDERING MODE ===")
        print(f"Total cases in folder: {total_all}")
        print(f"Processing cases: {START_CASE} to {MAX_CASES} ({total} cases)")
        print(f"Active render types: {active_render_types}")

        # 전체 렌더링 통계 계산
        total_renders_all_models = total * active_render_types * (30 if Sequence else 10)
        completed_renders_all = 0
        
        for idx, selected_folder in enumerate(case_folders, START_CASE):
            case_start_time = time.time()
            print(f"\n[{idx}/{MAX_CASES}] Processing: {selected_folder}")
            case_path = os.path.join(self.folder_path, selected_folder)
            if not os.path.isdir(case_path):
                continue
                
            # OBJ/JSON 파일 찾기
            obj_file, json_file = self._find_obj_json_files(case_path)
            if not obj_file or not json_file:
                self.report({"WARNING"}, f"{case_path}: OBJ 또는 JSON 파일을 찾을 수 없습니다.")
                continue

            # 메시 로드 및 설정
            mesh, obj = self._load_and_setup_mesh(obj_file, json_file, materials)
            file_prefix = f"{parent_folder}_{selected_folder}"
            
            # === 렌더링 타입 우선 방식 ===
            case_completed_renders = self._render_by_type_priority(scene, mesh, obj, materials, camera_positions, 
                                        file_prefix, output_base, target, idx, total, 
                                        active_render_types, start_time, completed_renders_all, total_renders_all_models)
            
            completed_renders_all += case_completed_renders

            # 케이스 완료 시간 출력
            case_time = time.time() - case_start_time
            print(f"  Case completed in {case_time:.1f}s")

        total_time = time.time() - start_time
        print(f"\n렌더링 완료! 총 소요시간: {self._format_time(total_time)}")

        # 완료 메시지 및 파일 탐색기 열기
        self._show_completion_message(output_base)
        return {"FINISHED"}

    def _create_materials(self):
        """모든 머티리얼을 미리 생성"""
        materials = {}
        
        # === 잇몸 머티리얼 (AO 노드 적용) ===
        mat_gum = bpy.data.materials.get("Gingiva_mat") or bpy.data.materials.new("Gingiva_mat")
        mat_gum.use_nodes = True
        nodes_gum = mat_gum.node_tree.nodes
        links_gum = mat_gum.node_tree.links
        nodes_gum.clear()

        # Principled BSDF 노드
        principled_gum = nodes_gum.new(type="ShaderNodeBsdfPrincipled")
        principled_gum.location = (0, 0)

        # 안전한 입력 설정 (버전 호환성)
        try:
            principled_gum.inputs["Base Color"].default_value = (1.0, 0.196, 0.282, 1.0)  # #FF3248FF
        except KeyError:
            try:
                principled_gum.inputs["Color"].default_value = (1.0, 0.196, 0.282, 1.0)
            except KeyError:
                principled_gum.inputs[0].default_value = (1.0, 0.196, 0.282, 1.0)

        try:
            principled_gum.inputs["Roughness"].default_value = 0.2
        except KeyError:
            principled_gum.inputs[7].default_value = 0.2

        # AO 노드 추가
        ao_node_gum = nodes_gum.new(type="ShaderNodeAmbientOcclusion")
        ao_node_gum.location = (-300, 0)
        ao_node_gum.inputs["Distance"].default_value = 2000.0
        ao_node_gum.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)

        # Mix RGB 노드 (AO와 메인 색상 혼합)
        mix_node_gum = nodes_gum.new(type="ShaderNodeMixRGB")
        mix_node_gum.location = (-150, 0)
        mix_node_gum.blend_type = "DARKEN"
        mix_node_gum.inputs[0].default_value = 0.8  # AO 강도
        mix_node_gum.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)  # 흰색 (color1)
        mix_node_gum.inputs[2].default_value = (1.0, 0.1177, 0.1518, 1.0)  # color2

        # Material Output 노드
        output_gum = nodes_gum.new(type="ShaderNodeOutputMaterial")
        output_gum.location = (200, 0)

        # 노드 연결 (안전한 연결)
        try:
            links_gum.new(ao_node_gum.outputs["AO"], mix_node_gum.inputs[0])
            links_gum.new(mix_node_gum.outputs[0], principled_gum.inputs["Base Color"])
            links_gum.new(principled_gum.outputs["BSDF"], output_gum.inputs["Surface"])
        except KeyError:
            links_gum.new(ao_node_gum.outputs[0], mix_node_gum.inputs[0])
            links_gum.new(mix_node_gum.outputs[0], principled_gum.inputs[0])
            links_gum.new(principled_gum.outputs[0], output_gum.inputs[0])

        # === 치아 머티리얼 (이미지 구조대로 수정) ===
        mat_tooth = bpy.data.materials.get("Teeth_mat") or bpy.data.materials.new("Teeth_mat")
        mat_tooth.use_nodes = True
        nodes_tooth = mat_tooth.node_tree.nodes
        links_tooth = mat_tooth.node_tree.links
        nodes_tooth.clear()

        # Principled BSDF 노드
        principled = nodes_tooth.new(type="ShaderNodeBsdfPrincipled")
        principled.location = (0, 0)

        # 안전한 입력 설정 (버전 호환성)
        try:
            principled.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        except KeyError:
            try:
                principled.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            except KeyError:
                principled.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

        try:
            principled.inputs["Roughness"].default_value = 0.1
        except KeyError:
            principled.inputs[7].default_value = 0.1

        try:
            principled.inputs["Metallic"].default_value = 0.0
        except KeyError:
            principled.inputs[6].default_value = 0.0

        # Coat 속성 추가 (촉촉한 느낌) - 안전한 설정
        try:
            principled.inputs["Coat Weight"].default_value = 0.8
            principled.inputs["Coat Roughness"].default_value = 0.05
            principled.inputs["Coat IOR"].default_value = 1.5
        except KeyError:
            pass

        # Subsurface Scattering 속성 추가 (치아 내부 빛 산란 효과)
        principled.inputs["Subsurface Weight"].default_value = 1.0
        principled.inputs["Subsurface Radius"].default_value = (0.1, 0.1, 0.1)
        principled.inputs["Subsurface Scale"].default_value = 10.0
        principled.inputs["Subsurface Anisotropy"].default_value = 0.0
        principled.inputs["Transmission Weight"].default_value = 0.1

        # === AO 노드들 (치아용) ===
        ao_node_tooth = nodes_tooth.new(type="ShaderNodeAmbientOcclusion")
        ao_node_tooth.location = (-600, 100)
        ao_node_tooth.inputs["Distance"].default_value = 2000.0
        ao_node_tooth.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)

        ao_node_gum2 = nodes_tooth.new(type="ShaderNodeAmbientOcclusion")
        ao_node_gum2.location = (-600, -100)
        ao_node_gum2.inputs["Distance"].default_value = 20000.0
        ao_node_gum2.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)

        # === Power 노드들 ===
        power_node_tooth = nodes_tooth.new(type="ShaderNodeMath")
        power_node_tooth.location = (-450, 100)
        power_node_tooth.operation = "POWER"
        power_node_tooth.inputs[1].default_value = 3.0

        power_node_gum2 = nodes_tooth.new(type="ShaderNodeMath")
        power_node_gum2.location = (-450, -100)
        power_node_gum2.operation = "POWER"
        power_node_gum2.inputs[1].default_value = 10.0

        # === Mix 노드들 ===
        mix_node_tooth = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_tooth.location = (-300, 100)
        mix_node_tooth.blend_type = "MULTIPLY"
        mix_node_tooth.inputs[0].default_value = 0.3
        mix_node_tooth.inputs[1].default_value = (1.0, 0.890, 0.498, 1.0)  # #FFE37FFF
        mix_node_tooth.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)

        mix_node_gum2 = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_gum2.location = (-300, -100)
        mix_node_gum2.blend_type = "MIX"
        mix_node_gum2.inputs[0].default_value = 0.8
        mix_node_gum2.inputs[1].default_value = (1.0, 1.0, 0.0, 1.0)
        mix_node_gum2.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)

        mix_node_extra = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_extra.location = (-150, -100)
        mix_node_extra.blend_type = "MIX"
        mix_node_extra.inputs[0].default_value = 0.5
        mix_node_extra.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
        mix_node_extra.inputs[2].default_value = (1.0, 0.8, 0.31, 1.0)

        main_mix_node = nodes_tooth.new(type="ShaderNodeMixRGB")
        main_mix_node.location = (0, 0)
        main_mix_node.blend_type = "COLOR"
        main_mix_node.inputs[0].default_value = 0.5

        # Material Output 노드
        output = nodes_tooth.new(type="ShaderNodeOutputMaterial")
        output.location = (200, 0)

        # 노드 연결 (안전한 연결)
        try:
            links_tooth.new(ao_node_tooth.outputs["AO"], power_node_tooth.inputs[0])
            links_tooth.new(power_node_tooth.outputs[0], mix_node_tooth.inputs[1])
            links_tooth.new(mix_node_tooth.outputs[0], main_mix_node.inputs[1])

            links_tooth.new(ao_node_gum2.outputs["AO"], power_node_gum2.inputs[0])
            links_tooth.new(power_node_gum2.outputs[0], mix_node_gum2.inputs[0])
            links_tooth.new(mix_node_gum2.outputs[0], mix_node_extra.inputs[0])
            links_tooth.new(mix_node_extra.outputs[0], main_mix_node.inputs[2])

            links_tooth.new(main_mix_node.outputs[0], principled.inputs["Base Color"])
            links_tooth.new(principled.outputs["BSDF"], output.inputs["Surface"])
        except KeyError:
            links_tooth.new(ao_node_tooth.outputs[0], power_node_tooth.inputs[0])
            links_tooth.new(power_node_tooth.outputs[0], mix_node_tooth.inputs[1])
            links_tooth.new(mix_node_tooth.outputs[0], main_mix_node.inputs[1])

            links_tooth.new(ao_node_gum2.outputs[0], power_node_gum2.inputs[0])
            links_tooth.new(power_node_gum2.outputs[0], mix_node_gum2.inputs[0])
            links_tooth.new(mix_node_gum2.outputs[0], mix_node_extra.inputs[0])
            links_tooth.new(mix_node_extra.outputs[0], main_mix_node.inputs[2])

            links_tooth.new(main_mix_node.outputs[0], principled.inputs[0])
            links_tooth.new(principled.outputs[0], output.inputs[0])

        # === Unlit 머티리얼들 ===
        mat_gum_unlit = bpy.data.materials.get("Gingiva_unlit")
        if not mat_gum_unlit:
            mat_gum_unlit = bpy.data.materials.new("Gingiva_unlit")
            mat_gum_unlit.use_nodes = True
            nodes_gum = mat_gum_unlit.node_tree.nodes
            links_gum = mat_gum_unlit.node_tree.links
            nodes_gum.clear()
            emission_gum = nodes_gum.new(type="ShaderNodeEmission")
            emission_gum.inputs["Color"].default_value = (1.0, 0.0, 0.0, 1.0)
            output_gum = nodes_gum.new(type="ShaderNodeOutputMaterial")
            links_gum.new(emission_gum.outputs["Emission"], output_gum.inputs["Surface"])

        mat_tooth_unlit = bpy.data.materials.get("Tooth_unlit")
        if not mat_tooth_unlit:
            mat_tooth_unlit = bpy.data.materials.new("Tooth_unlit")
            mat_tooth_unlit.use_nodes = True
            nodes_tooth = mat_tooth_unlit.node_tree.nodes
            links_tooth = mat_tooth_unlit.node_tree.links
            nodes_tooth.clear()
            emission_tooth = nodes_tooth.new(type="ShaderNodeEmission")
            emission_tooth.inputs["Color"].default_value = (1.0, 1.0, 0.0, 1.0)
            output_tooth = nodes_tooth.new(type="ShaderNodeOutputMaterial")
            links_tooth.new(emission_tooth.outputs["Emission"], output_tooth.inputs["Surface"])

        # === Matt 머티리얼들 ===
        mat_gum_matt = bpy.data.materials.get("Gingiva_matt")
        if not mat_gum_matt:
            mat_gum_matt = bpy.data.materials.new("Gingiva_matt")
            mat_gum_matt.use_nodes = True
            nodes_gum_matt = mat_gum_matt.node_tree.nodes
            links_gum_matt = mat_gum_matt.node_tree.links
            nodes_gum_matt.clear()

            principled_gum_matt = nodes_gum_matt.new(type="ShaderNodeBsdfPrincipled")
            principled_gum_matt.location = (0, 0)

            try:
                principled_gum_matt.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            except KeyError:
                try:
                    principled_gum_matt.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
                except KeyError:
                    principled_gum_matt.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

            try:
                principled_gum_matt.inputs["Roughness"].default_value = 0.5
            except KeyError:
                principled_gum_matt.inputs[7].default_value = 0.5

            output_gum_matt = nodes_gum_matt.new(type="ShaderNodeOutputMaterial")
            output_gum_matt.location = (200, 0)

            try:
                links_gum_matt.new(principled_gum_matt.outputs["BSDF"], output_gum_matt.inputs["Surface"])
            except KeyError:
                links_gum_matt.new(principled_gum_matt.outputs[0], output_gum_matt.inputs[0])

        mat_tooth_matt = bpy.data.materials.get("Tooth_matt")
        if not mat_tooth_matt:
            mat_tooth_matt = bpy.data.materials.new("Tooth_matt")
            mat_tooth_matt.use_nodes = True
            nodes_tooth_matt = mat_tooth_matt.node_tree.nodes
            links_tooth_matt = mat_tooth_matt.node_tree.links
            nodes_tooth_matt.clear()

            principled_tooth_matt = nodes_tooth_matt.new(type="ShaderNodeBsdfPrincipled")
            principled_tooth_matt.location = (0, 0)

            try:
                principled_tooth_matt.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            except KeyError:
                try:
                    principled_tooth_matt.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
                except KeyError:
                    principled_tooth_matt.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

            try:
                principled_tooth_matt.inputs["Roughness"].default_value = 0.5
            except KeyError:
                principled_tooth_matt.inputs[7].default_value = 0.5

            output_tooth_matt = nodes_tooth_matt.new(type="ShaderNodeOutputMaterial")
            output_tooth_matt.location = (200, 0)

            try:
                links_tooth_matt.new(principled_tooth_matt.outputs["BSDF"], output_tooth_matt.inputs["Surface"])
            except KeyError:
                links_tooth_matt.new(principled_tooth_matt.outputs[0], output_tooth_matt.inputs[0])

        # === Curvature 머티리얼 ===
        mat_curvature = bpy.data.materials.get("Curvature_mat")
        if not mat_curvature:
            mat_curvature = bpy.data.materials.new("Curvature_mat")
            mat_curvature.use_nodes = True
            nodes_curv = mat_curvature.node_tree.nodes
            links_curv = mat_curvature.node_tree.links
            nodes_curv.clear()

            geom = nodes_curv.new(type="ShaderNodeNewGeometry")
            geom.location = (-400, 0)

            # 대비 강화를 위한 Power 노드 추가 (Pointiness^2.9)
            power_curv = nodes_curv.new(type="ShaderNodeMath")
            power_curv.location = (-300, 0)
            power_curv.operation = "POWER"
            power_curv.inputs[1].default_value = 2.9

            ramp = nodes_curv.new(type="ShaderNodeValToRGB")
            ramp.location = (-200, 0)
            try:
                ramp.color_ramp.elements[0].position = 0.094
                ramp.color_ramp.elements[1].position = 0.188
            except Exception:
                pass

            emission = nodes_curv.new(type="ShaderNodeEmission")
            emission.location = (0, 0)

            out_curv = nodes_curv.new(type="ShaderNodeOutputMaterial")
            out_curv.location = (200, 0)

            # 연결: Pointiness -> Power -> ColorRamp -> Emission -> Output
            try:
                links_curv.new(geom.outputs["Pointiness"], power_curv.inputs[0])
                links_curv.new(power_curv.outputs[0], ramp.inputs[0])
            except Exception:
                links_curv.new(geom.outputs[6], power_curv.inputs[0])
                links_curv.new(power_curv.outputs[0], ramp.inputs[0])
            links_curv.new(ramp.outputs[0], emission.inputs[0])
            try:
                links_curv.new(emission.outputs["Emission"], out_curv.inputs["Surface"])
            except Exception:
                links_curv.new(emission.outputs[0], out_curv.inputs[0])

        materials = {
            'gum': mat_gum,
            'tooth': mat_tooth,
            'gum_unlit': mat_gum_unlit,
            'tooth_unlit': mat_tooth_unlit,
            'gum_matt': mat_gum_matt,
            'tooth_matt': mat_tooth_matt,
            'curvature': mat_curvature
        }
        
        return materials

    def _find_obj_json_files(self, case_path):
        """OBJ와 JSON 파일을 찾아서 반환"""
        obj_file = None
        json_file = None
        for f in os.listdir(case_path):
            if f.endswith(".obj"):
                obj_file = os.path.join(case_path, f)
            elif f.endswith(".json"):
                json_file = os.path.join(case_path, f)
        return obj_file, json_file

    def _load_and_setup_mesh(self, obj_file, json_file, materials):
        """메시 로드 및 설정"""
        # 씬 정리 (머티리얼 삭제 X)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        for block in bpy.data.meshes:
            bpy.data.meshes.remove(block, do_unlink=True)
        for block in bpy.data.lights:
            bpy.data.lights.remove(block, do_unlink=True)
        for block in bpy.data.cameras:
            bpy.data.cameras.remove(block, do_unlink=True)

        # OBJ 임포트
        bpy.ops.wm.obj_import(filepath=obj_file)
        obj = bpy.context.selected_objects[0]
        mesh = obj.data

        # 머티리얼 슬롯 항상 2개로 초기화
        mesh.materials.clear()
        mesh.materials.append(materials['gum_unlit'])
        mesh.materials.append(materials['tooth_unlit'])

        # material_index 할당 (잇몸: 0, 치아: 1)
        with open(json_file) as f:
            meta = json.load(f)
        labels = meta["labels"]
        for poly in mesh.polygons:
            face_labels = [labels[v] for v in poly.vertices]
            if all(l == 0 for l in face_labels):
                poly.material_index = 0
            elif all(l > 0 for l in face_labels):
                poly.material_index = 1
                
        return mesh, obj

    def _render_by_type_priority(self, scene, mesh, obj, materials, camera_positions, 
                               file_prefix, output_base, target, idx, total, 
                               active_render_types, start_time, completed_renders_all, total_renders_all_models):
        """렌더링 타입 우선 방식으로 렌더링"""
        
        # 카메라 위치들 생성 (Sequence 모드 처리 포함)
        camera_data = self._generate_camera_positions(camera_positions, target)
        
        # 렌더링 타입별 디렉토리 매핑
        render_configs = []
        if RENDER_UNLIT:
            render_configs.append(('unlit', os.path.join(output_base, "unlit"), 'BLENDER_EEVEE_NEXT', 
                                 materials['gum_unlit'], materials['tooth_unlit'], False, None))
        if RENDER_MATT:
            render_configs.append(('matt', os.path.join(output_base, "matt"), 'BLENDER_EEVEE_NEXT', 
                                 materials['gum_matt'], materials['tooth_matt'], False, None))
        if RENDER_LIT:
            render_configs.append(('lit', os.path.join(output_base, "lit"), 'CYCLES', 
                                 materials['gum'], materials['tooth'], True, None))
        if RENDER_DEPTH:
            render_configs.append(('depth', os.path.join(output_base, "depth"), 'BLENDER_EEVEE_NEXT', 
                                 None, None, False, 'depth'))
        if RENDER_NORMAL:
            render_configs.append(('normal', os.path.join(output_base, "normal"), 'BLENDER_EEVEE_NEXT', 
                                 None, None, False, 'normal'))
        if RENDER_CURVATURE:
            render_configs.append(('curvature', os.path.join(output_base, "curvature"), 'CYCLES', 
                                 materials['curvature'], materials['curvature'], False, None))
        
        total_renders = len(camera_data) * len(render_configs)
        completed_renders = 0
        
        print(f"  Rendering {len(camera_data)} views × {len(render_configs)} types = {total_renders} images")
        
        # 렌더링 타입별 루프 (외부)
        for render_type_idx, render_config in enumerate(render_configs):
            render_type, output_dir, engine, mat_gum, mat_tooth, use_shadow, pass_type = render_config
            
            print(f"  [{idx}/{MAX_CASES}] [{render_type_idx+1}/{len(render_configs)}] Starting {render_type.upper()} rendering ({engine})")
            
            # 엔진 설정 (한 번만)
            scene.render.engine = engine
            scene.use_nodes = False
            
            # 머티리얼 설정 (한 번만)
            if mat_gum and mat_tooth:
                mesh.materials[0] = mat_gum
                mesh.materials[1] = mat_tooth
            elif render_type == 'curvature':
                mesh.materials[0] = materials['curvature']
                if len(mesh.materials) > 1:
                    mesh.materials[1] = materials['curvature']
            
            # 카메라별 루프 (내부)
            for view_idx, (view_name, cam_pos) in enumerate(camera_data):
                # 카메라 생성
                cam_data = bpy.data.cameras.new(view_name + "_cam")
                cam_obj = bpy.data.objects.new(view_name + "_cam", cam_data)
                bpy.context.collection.objects.link(cam_obj)
                cam_obj.location = cam_pos
                direction = target - cam_pos
                rot_quat = direction.to_track_quat("-Z", "Y")
                cam_obj.rotation_euler = rot_quat.to_euler()
                bpy.context.scene.camera = cam_obj
                cam_data.angle = math.radians(60)
                
                # 라이트 생성
                light_data = bpy.data.lights.new(view_name + "_sun", type="SUN")
                light_data.energy = 5
                light_data.use_shadow = use_shadow
                light_obj = bpy.data.objects.new(view_name + "_sun", light_data)
                bpy.context.collection.objects.link(light_obj)
                light_obj.parent = cam_obj
                
                # 렌더링 실행
                if render_type in ['depth', 'normal']:
                    self._render_pass(scene, cam_obj, obj, render_type, output_dir, file_prefix, view_name)
                else:
                    # 일반 렌더링
                    output_path = os.path.join(output_dir, f"{file_prefix}_{view_name}.png")
                    scene.render.filepath = output_path
                    bpy.ops.render.render(write_still=True)
                
                # 카메라와 라이트 정리
                bpy.data.objects.remove(cam_obj, do_unlink=True)
                bpy.data.objects.remove(light_obj, do_unlink=True)
                
                completed_renders += 1
                
                # 진행률 출력 (각 카메라 뷰마다) - 전체 모델 기준
                current_total_renders = completed_renders_all + completed_renders
                elapsed_time = time.time() - start_time
                avg_time_per_render = elapsed_time / current_total_renders if current_total_renders > 0 else 0
                remaining_renders_all = total_renders_all_models - current_total_renders
                estimated_remaining_time = remaining_renders_all * avg_time_per_render
                
                print(f"    [{idx}/{MAX_CASES}] {render_type.upper()}: {view_idx+1}/{len(camera_data)} views | "
                      f"Model: {completed_renders}/{total_renders} ({completed_renders/total_renders*100:.1f}%) | "
                      f"Overall: {current_total_renders}/{total_renders_all_models} ({current_total_renders/total_renders_all_models*100:.1f}%) | "
                      f"ETA: {self._format_time(estimated_remaining_time)}")
            
            print(f"  [{idx}/{MAX_CASES}] [{render_type_idx+1}/{len(render_configs)}] Completed {render_type.upper()} rendering")
            
            # GPU 메모리 정리 (Cycles 렌더링 후)
            if engine == 'CYCLES':
                self._cleanup_gpu_memory()
        
        return completed_renders

    def _cleanup_gpu_memory(self):
        """GPU 메모리 정리 및 안정성 향상"""
        try:
            # GPU 메모리 정리
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            
            # Cycles GPU 메모리 정리
            if hasattr(bpy.context.scene, 'cycles') and bpy.context.scene.cycles.device == 'GPU':
                # GPU 컨텍스트 새로고침
                bpy.context.scene.cycles.device = 'CPU'
                bpy.context.scene.cycles.device = 'GPU'
                
            # 가비지 컬렉션 강제 실행
            import gc
            gc.collect()
            
        except Exception as e:
            print(f"GPU 메모리 정리 중 오류: {e}")

    def _generate_camera_positions(self, camera_positions, target):
        """카메라 위치들을 생성 (Sequence 모드 처리 포함)"""
        if Sequence:
            # Sequence 모드: top->left->bottom 보간으로 30장 생성
            total_sequence_frames = 30
            frames_per_segment = 15  # top->left: 15장, left->bottom: 15장
            
            camera_data = []
            for frame_idx in range(total_sequence_frames):
                # 프레임 인덱스에 따라 보간 계산
                if frame_idx < frames_per_segment:
                    # top -> left 보간 (0~14)
                    t = frame_idx / (frames_per_segment - 1)
                    start_pos = camera_positions[0][1]  # top
                    end_pos = camera_positions[1][1]    # left
                    cam_pos = start_pos.lerp(end_pos, t)
                    view_name = f"sequence_{frame_idx:02d}"
                else:
                    # left -> bottom 보간 (15~29)
                    t = (frame_idx - frames_per_segment) / (frames_per_segment - 1)
                    start_pos = camera_positions[1][1]  # left
                    end_pos = camera_positions[2][1]    # bottom
                    cam_pos = start_pos.lerp(end_pos, t)
                    view_name = f"sequence_{frame_idx:02d}"
                
                camera_data.append((view_name, cam_pos))
            
            return camera_data
        else:
            # 기존 모드: 카메라 위치 그대로 사용
            return camera_positions

    def _render_pass(self, scene, cam_obj, obj, pass_type, output_dir, file_prefix, view_name):
        """패스 기반 렌더링 (depth, normal)"""
        if pass_type == 'depth':
            # 화면 기준(카메라 공간) 깊이 최소/최대 계산
            def compute_obj_depth_range_screen(obj_local, cam_local):
                cam_inv = cam_local.matrix_world.inverted()
                min_d, max_d = None, None
                for v in obj_local.data.vertices:
                    world_co = obj_local.matrix_world @ v.co
                    cam_co = cam_inv @ world_co
                    depth_val = -cam_co.z  # 카메라가 -Z를 바라봄
                    if min_d is None or depth_val < min_d:
                        min_d = depth_val
                    if max_d is None or depth_val > max_d:
                        max_d = depth_val
                if min_d is None or max_d is None:
                    return 0.0, 1.0
                min_d = max(min_d, 0.0)
                if max_d <= min_d:
                    max_d = min_d + 1.0
                return float(min_d), float(max_d)

            near_d, far_d = compute_obj_depth_range_screen(obj, cam_obj)

            # 뷰에 맞춰 카메라 클리핑 범위를 메시 범위로 세팅
            depth_range = max(far_d - near_d, 1e-3)
            margin = max(0.01, depth_range * 0.05)
            cam_data = cam_obj.data
            cam_data.clip_start = max(0.001, near_d - margin)
            cam_data.clip_end = far_d + margin

            view_layer = bpy.context.view_layer
            try:
                view_layer.use_pass_z = True
            except Exception:
                pass

            # 컴포지터: Depth -> Normalize -> Composite
            prev_use_nodes = scene.use_nodes
            scene.use_nodes = True
            ntree = scene.node_tree
            nodes = ntree.nodes
            links = ntree.links
            nodes.clear()
            rl = nodes.new(type="CompositorNodeRLayers")
            z_norm = nodes.new(type="CompositorNodeNormalize")
            comp = nodes.new(type="CompositorNodeComposite")
            links.new(rl.outputs["Depth"], z_norm.inputs[0])
            links.new(z_norm.outputs[0], comp.inputs["Image"])

            img_settings = scene.render.image_settings
            prev_format = img_settings.file_format
            prev_color_mode = img_settings.color_mode
            prev_color_depth = img_settings.color_depth
            prev_view_transform = scene.view_settings.view_transform

            img_settings.file_format = "PNG"
            img_settings.color_mode = "BW"
            img_settings.color_depth = "16"
            scene.view_settings.view_transform = "Standard"

            depth_path = os.path.join(output_dir, f"{file_prefix}_{view_name}.png")
            scene.render.filepath = depth_path
            scene.render.engine = "BLENDER_EEVEE_NEXT"
            bpy.ops.render.render(write_still=True, use_viewport=False)

            # 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
            scene.view_settings.view_transform = prev_view_transform
            scene.use_nodes = prev_use_nodes

        elif pass_type == 'normal':
            # EEVEE 엔진으로 설정
            scene.render.engine = "BLENDER_EEVEE_NEXT"

            # 라이팅 효과 완전히 제거
            lights = [obj for obj in bpy.context.scene.objects if obj.type == 'LIGHT']
            for light in lights:
                if hasattr(light.data, 'use_shadow'):
                    light.data.use_shadow = False
                if hasattr(light.data, 'energy'):
                    light.data.energy = 0.0

            # 노멀 패스 활성화
            view_layer = bpy.context.view_layer
            try:
                view_layer.use_pass_normal = True
            except Exception:
                pass

            # 컴포지터: Normal -> Composite
            prev_use_nodes = scene.use_nodes
            scene.use_nodes = True
            ntree = scene.node_tree
            nodes = ntree.nodes
            links = ntree.links
            nodes.clear()

            # Render Layers 노드
            rl = nodes.new(type="CompositorNodeRLayers")

            # Math 노드들로 노멀을 0-1 범위로 변환
            separate_xyz = nodes.new(type="CompositorNodeSeparateXYZ")
            separate_xyz.location = (200, 0)

            # X, Y, Z 각각을 0-1 범위로 변환 ([-1,1] -> [0,1])
            math_x = nodes.new(type="CompositorNodeMath")
            math_x.operation = "MULTIPLY_ADD"
            math_x.inputs[1].default_value = 0.5  # multiply by 0.5
            math_x.inputs[2].default_value = 0.5  # add 0.5
            math_x.location = (400, 100)

            math_y = nodes.new(type="CompositorNodeMath")
            math_y.operation = "MULTIPLY_ADD"
            math_y.inputs[1].default_value = 0.5
            math_y.inputs[2].default_value = 0.5
            math_y.location = (400, 0)

            math_z = nodes.new(type="CompositorNodeMath")
            math_z.operation = "MULTIPLY_ADD"
            math_z.inputs[1].default_value = 0.5
            math_z.inputs[2].default_value = 0.5
            math_z.location = (400, -100)

            # 다시 XYZ로 결합
            combine_xyz = nodes.new(type="CompositorNodeCombineXYZ")
            combine_xyz.location = (600, 0)

            # Composite 노드
            comp = nodes.new(type="CompositorNodeComposite")
            comp.location = (800, 0)

            # 노드 연결
            links.new(rl.outputs["Normal"], separate_xyz.inputs[0])
            links.new(separate_xyz.outputs["X"], math_x.inputs[0])
            links.new(separate_xyz.outputs["Y"], math_y.inputs[0])
            links.new(separate_xyz.outputs["Z"], math_z.inputs[0])
            links.new(math_x.outputs[0], combine_xyz.inputs["X"])
            links.new(math_y.outputs[0], combine_xyz.inputs["Y"])
            links.new(math_z.outputs[0], combine_xyz.inputs["Z"])
            links.new(combine_xyz.outputs[0], comp.inputs["Image"])

            # 이미지 설정
            img_settings = scene.render.image_settings
            prev_format = img_settings.file_format
            prev_color_mode = img_settings.color_mode
            prev_color_depth = img_settings.color_depth
            prev_view_transform = scene.view_settings.view_transform

            img_settings.file_format = "PNG"
            img_settings.color_mode = "RGB"
            img_settings.color_depth = "8"
            scene.view_settings.view_transform = "Standard"

            normal_path = os.path.join(output_dir, f"{file_prefix}_{view_name}.png")
            scene.render.filepath = normal_path
            bpy.ops.render.render(write_still=True, use_viewport=False)

            # 설정 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
            scene.view_settings.view_transform = prev_view_transform
            scene.use_nodes = prev_use_nodes

    def _format_time(self, seconds):
        """시간을 시:분:초 형식으로 변환"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def _show_completion_message(self, output_base):
        """완료 메시지 및 파일 탐색기 열기"""
        # 활성화된 렌더링 타입에 따른 완료 메시지 생성
        completed_dirs = []
        if RENDER_LIT:
            completed_dirs.append("lit")
        if RENDER_UNLIT:
            completed_dirs.append("unlit")
        if RENDER_MATT:
            completed_dirs.append("matt")
        if RENDER_DEPTH:
            completed_dirs.append("depth")
        if RENDER_NORMAL:
            completed_dirs.append("normal")
        if RENDER_CURVATURE:
            completed_dirs.append("curvature")

        self.report(
            {"INFO"},
            f"모든 케이스 이미지 저장 완료: {', '.join(completed_dirs)}",
        )

        # 파일 탐색기 열기 (첫 번째 활성화된 폴더 기준)
        first_active_dir = None
        if RENDER_LIT:
            first_active_dir = os.path.join(output_base, "lit")
        elif RENDER_UNLIT:
            first_active_dir = os.path.join(output_base, "unlit")
        elif RENDER_MATT:
            first_active_dir = os.path.join(output_base, "matt")
        elif RENDER_DEPTH:
            first_active_dir = os.path.join(output_base, "depth")
        elif RENDER_NORMAL:
            first_active_dir = os.path.join(output_base, "normal")
        elif RENDER_CURVATURE:
            first_active_dir = os.path.join(output_base, "curvature")
        else:
            first_active_dir = output_base  # 기본 출력 폴더

        if first_active_dir and os.path.exists(first_active_dir):
            if sys.platform == "win32":
                os.startfile(first_active_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", first_active_dir])
            else:
                subprocess.Popen(["xdg-open", first_active_dir])

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)


def menu_func(self, context):
    self.layout.operator(OT_SelectFolderAndColorize.bl_idname)


def register():
    bpy.utils.register_class(OT_SelectFolderAndColorize)
    bpy.types.TOPBAR_MT_file.append(menu_func)


def unregister():
    bpy.utils.unregister_class(OT_SelectFolderAndColorize)
    bpy.types.TOPBAR_MT_file.remove(menu_func)


if __name__ == "__main__":
    register()

# 512x512
# depth map
# Optimized rendering: Render type priority (각 렌더링 타입별로 모든 카메라 각도 처리)
