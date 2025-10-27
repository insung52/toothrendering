import bpy
import os
import json
import mathutils
import math
import subprocess
import sys
import time

'''
카메라의 위치, 각도
extrinsic 
rotation, translation

intrinsic projection matrix, view matrix 총 5개
렌더링 
'''

# 설정 변수
MAX_CASES = 100  # 처리할 최대 케이스 수
START_CASE = 1  # 시작 케이스 번호 (1부터 시작)
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
            # Sequence 모드: 8×5=40개 카메라 각도 생성
            # 기본 벡터 (0, -1, -1)을 기준으로
            # 1. X축 중심으로 -20, -10, 0, 10, 20도 회전 (각도 단위)
            # 2. Y축 중심으로 0, 45, 90, 135, 180, 225, 270, 315도 회전 (각도 단위)
            camera_positions = []
            x_angles = [0, 45, 90, 135, 180, 225, 270, 315]  # Y축 중심 회전 (도)
            z_angle_offsets = [-20, -10, 0, 10, 20]  # X축 중심 회전 (도)
            
            # 기본 벡터 (0, -1, -1)
            base_vec = mathutils.Vector((0, -1, 0))
            
            for z_idx, x_angle_offset in enumerate(z_angle_offsets):
                # 먼저 X축 중심으로 회전
                if x_angle_offset == 0:
                    vec_after_x = base_vec
                else:
                    x_rotation_rad = math.radians(x_angle_offset)
                    x_rotation_matrix = mathutils.Matrix.Rotation(x_rotation_rad, 3, 'X')
                    vec_after_x = x_rotation_matrix @ base_vec
                
                # 그 다음 Y축 중심으로 8번 회전 (0, 45, 90, ... 315도)
                for x_idx, y_angle in enumerate(x_angles):
                    if y_angle == 0:
                        rotated_vec = vec_after_x
                    else:
                        y_rotation_rad = math.radians(y_angle)
                        y_rotation_matrix = mathutils.Matrix.Rotation(y_rotation_rad, 3, 'Z')
                        rotated_vec = y_rotation_matrix @ vec_after_x
                    
                    # 정규화
                    rotated_vec = rotated_vec.normalized()
                    cam_pos = target + rotated_vec * distance
                    
                    # 파일명 생성
                    name = f"z_{x_idx:02d}_x{x_angle_offset:+03d}"
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

        # === 카메라 파라미터 추출 (Sequence 모드일 때만) ===
        self._extract_camera_parameters(scene, camera_positions, target, output_base)

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
        total_renders_all_models = total * active_render_types * (40 if Sequence else 10)
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

        # 메시 변환: X축 -45도 회전 후 Z축 +70 이동
        # 1. 먼저 X축 회전 (월드 기준)
        obj.rotation_euler.x += math.radians(-45)
        
        # 2. 회전된 상태에서 Z축 위로 +70 이동
        # 회전된 좌표계의 Z축 방향으로 이동
        up_vector = mathutils.Vector((0, 29.29, 70))
        obj.location += up_vector
        
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
                
                # Depth 렌더링을 위한 카메라 clip 범위 설정
                if render_type in ['depth', 'normal']:

                    min_depth = 50
                    max_depth = 150
                    
                
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
                    # 파일 형식 설정 (lit, normal은 WebP)
                    img_settings = scene.render.image_settings
                    prev_format = img_settings.file_format
                    prev_color_mode = img_settings.color_mode
                    prev_color_depth = img_settings.color_depth
                    
                    if render_type in ['lit', 'normal', 'unlit', 'matt', 'curvature']:
                        # WebP로 저장
                        img_settings.file_format = "WEBP"
                        file_ext = ".webp"
                    else:
                        # PNG로 저장
                        img_settings.file_format = "PNG"
                        file_ext = ".png"
                    
                    output_path = os.path.join(output_dir, f"{file_prefix}_{view_name}{file_ext}")
                    scene.render.filepath = output_path
                    bpy.ops.render.render(write_still=True)
                    
                    # 복구
                    img_settings.file_format = prev_format
                    img_settings.color_mode = prev_color_mode
                    img_settings.color_depth = prev_color_depth
                
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
            # Sequence 모드: 40개 카메라 각도 그대로 사용
            return camera_positions
        else:
            # 기존 모드: 카메라 위치 그대로 사용
            return camera_positions

    def _render_pass(self, scene, cam_obj, obj, pass_type, output_dir, file_prefix, view_name):
        """패스 기반 렌더링 (depth, normal)"""
        if pass_type == 'depth':
            # EEVEE에서 depth pass 활성화
            scene.render.engine = "BLENDER_EEVEE_NEXT"
            
            # View layer 설정 - depth pass 활성화
            view_layer = bpy.context.view_layer
            
            # EEVEE에서 depth pass 활성화하는 방법
            # 1. Combined pass 활성화
            view_layer.use_pass_combined = True
            
            # 2. Z (depth) pass 활성화 - EEVEE는 이것만으로 충분
            view_layer.use_pass_z = True
            
            # 3. Scene 업데이트
            bpy.context.view_layer.update()
            
            # 4. EEVEE가 depth pass를 렌더링하도록 확인
            # (EEVEE는 use_pass_z=True만 설정하면 자동으로 depth pass를 렌더링함)
            
            # EEVEE 설정 (안전하게)
            try:
                scene.eevee.taa_render_samples = 1  # 빠른 렌더링
            except:
                pass
            
            try:
                if hasattr(scene.eevee, 'use_ssr'):
                    scene.eevee.use_ssr = False
                if hasattr(scene.eevee, 'use_ssr_refraction'):
                    scene.eevee.use_ssr_refraction = False
            except:
                pass
            
            # 컴포지터 설정
            prev_use_nodes = scene.use_nodes
            scene.use_nodes = True
            ntree = scene.node_tree
            nodes = ntree.nodes
            links = ntree.links
            nodes.clear()
            
            # Render Layers 노드
            rl = nodes.new(type="CompositorNodeRLayers")
            rl.location = (-600, 0)
            
            # Map Range 노드로 [clip_start, clip_end]를 [0, 1]로 매핑
            map_range = nodes.new(type="CompositorNodeMapRange")
            map_range.location = (-400, 0)
            map_range.use_clamp = True
            
            # 카메라 clip 범위 설정
            cam_data = cam_obj.data
            map_range.inputs["From Min"].default_value = cam_data.clip_start  # 가까운 부분
            map_range.inputs["From Max"].default_value = cam_data.clip_end    # 먼 부분
            map_range.inputs["To Min"].default_value = 0.0   # 가까운 부분 → 검은색
            map_range.inputs["To Max"].default_value = 1.0   # 먼 부분 → 흰색 (inverted)
            
            # Composite 노드
            comp = nodes.new(type="CompositorNodeComposite")
            comp.location = (-200, 0)
            
            # 연결: Depth -> Map Range -> Composite
            links.new(rl.outputs["Depth"], map_range.inputs["Value"])
            links.new(map_range.outputs["Value"], comp.inputs["Image"])
            
            # 이미지 설정
            img_settings = scene.render.image_settings
            prev_format = img_settings.file_format
            prev_color_mode = img_settings.color_mode
            prev_color_depth = img_settings.color_depth
            
            if pass_type == 'depth':
                # Depth는 EXR 형식으로 저장 (32비트 float)
                img_settings.file_format = "OPEN_EXR"
                img_settings.color_mode = "BW"
                file_ext = ".exr"
            elif pass_type == 'normal':
                # Normal은 WebP 형식으로 저장
                img_settings.file_format = "WEBP"
                img_settings.color_mode = "RGB"
                file_ext = ".webp"
            
            depth_path = os.path.join(output_dir, f"{file_prefix}_{view_name}{file_ext}")
            scene.render.filepath = depth_path
            
            # 렌더링 실행
            bpy.ops.render.render(write_still=True, use_viewport=False)
            
            # 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
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

            # Normal은 WebP 형식으로 저장
            img_settings.file_format = "WEBP"
            img_settings.color_mode = "RGB"
            img_settings.color_depth = "8"
            scene.view_settings.view_transform = "Standard"

            normal_path = os.path.join(output_dir, f"{file_prefix}_{view_name}.webp")
            scene.render.filepath = normal_path
            bpy.ops.render.render(write_still=True, use_viewport=False)

            # 설정 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
            scene.view_settings.view_transform = prev_view_transform
            scene.use_nodes = prev_use_nodes

    def _extract_camera_parameters(self, scene, camera_positions, target, output_base):
        """카메라 파라미터 추출 및 JSON 저장 (Sequence 모드일 때만)"""
        if not Sequence:
            return
            
        print("=== 카메라 파라미터 추출 시작 ===")
        
        # 카메라 파라미터 저장 디렉토리 생성
        cameras_dir = os.path.join(output_base, "cameras")
        os.makedirs(cameras_dir, exist_ok=True)
        
        # 40개 카메라 포즈 생성
        camera_data = self._generate_camera_positions(camera_positions, target)
        
        # 공통 메타데이터
        resolution_x = scene.render.resolution_x
        resolution_y = scene.render.resolution_y
        pixel_aspect_x = scene.render.pixel_aspect_x
        pixel_aspect_y = scene.render.pixel_aspect_y
        
        # 카메라 데이터 배열
        views = []
        
        for view_idx, (view_name, cam_pos) in enumerate(camera_data):
            # 임시 카메라 생성
            cam_data = bpy.data.cameras.new(view_name + "_temp")
            cam_obj = bpy.data.objects.new(view_name + "_temp", cam_data)
            bpy.context.collection.objects.link(cam_obj)
            
            # 카메라 위치 및 회전 설정
            cam_obj.location = cam_pos
            direction = target - cam_pos
            rot_quat = direction.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()
            cam_data.angle = math.radians(60)
            
            # 카메라 변환 행렬 업데이트 강제
            bpy.context.view_layer.update()
            cam_obj.update_tag()
            
            # 카메라 파라미터 계산
            params = self._calculate_camera_params(scene, cam_obj, cam_data, resolution_x, resolution_y, pixel_aspect_x, pixel_aspect_y)
            params['view_name'] = view_name
            views.append(params)
            
            # 임시 카메라 정리
            bpy.data.objects.remove(cam_obj, do_unlink=True)
            bpy.data.cameras.remove(cam_data, do_unlink=True)
        
        # JSON 파일로 저장
        camera_params = {
            'metadata': {
                'total_views': len(views),
                'resolution': [resolution_x, resolution_y],
                'pixel_aspect': [pixel_aspect_x, pixel_aspect_y],
                'convention': 'Blender (-Z forward, +Y up)',
                'sequence_mode': True
            },
            'views': views
        }
        
        # 파일명을 카메라 개수에 맞춰 동적으로 생성
        json_filename = f"sequence_{len(views)}.json"
        json_path = os.path.join(cameras_dir, json_filename)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(camera_params, f, indent=2, ensure_ascii=False)
        
        print(f"카메라 파라미터 저장 완료: {json_path}")
        print(f"총 {len(views)}개 뷰의 파라미터 추출됨")

    def _calculate_camera_params(self, scene, cam_obj, cam_data, res_x, res_y, pixel_aspect_x, pixel_aspect_y):
        """개별 카메라의 파라미터 계산"""
        
        # === Intrinsic Parameters (K) ===
        # FOV에서 focal length 계산
        fov_rad = cam_data.angle
        focal_length_px = (res_y / 2.0) / math.tan(fov_rad / 2.0)
        
        # 픽셀 종횡비 반영
        fx = focal_length_px / pixel_aspect_x
        fy = focal_length_px / pixel_aspect_y
        
        # 주점 (이미지 중심 + shift)
        cx = res_x / 2.0 + cam_data.shift_x * res_x
        cy = res_y / 2.0 + cam_data.shift_y * res_y
        
        # 카메라 내참조 행렬 K
        K = [
            [fx, 0, cx],
            [0, fy, cy],
            [0, 0, 1]
        ]
        
        # === Extrinsic Parameters ===
        # 카메라 월드 행렬 (Camera to World)
        T_cw = [list(row) for row in cam_obj.matrix_world]
        
        # 회전 행렬 R (3x3)와 평행이동 벡터 t (3,)
        R = [list(row) for row in T_cw[:3][:3]]
        t = [T_cw[0][3], T_cw[1][3], T_cw[2][3]]
        
        # World to Camera 변환 (World to Camera)
        T_wc = [list(row) for row in cam_obj.matrix_world.inverted()]
        
        # === View Matrix (World to Camera) ===
        view_matrix = [list(row) for row in cam_obj.matrix_world.inverted()]
        
        # === Projection Matrix ===
        # OpenGL 스타일 투영 행렬 (perspective)
        near = cam_data.clip_start
        far = cam_data.clip_end
        
        # FOV 기반 투영 행렬 계산
        f = 1.0 / math.tan(fov_rad / 2.0)
        aspect = res_x / res_y
        
        projection_matrix = [
            [f/aspect, 0, 0, 0],
            [0, f, 0, 0],
            [0, 0, (far + near) / (near - far), (2 * far * near) / (near - far)],
            [0, 0, -1, 0]
        ]
        
        return {
            'intrinsic': {
                'K': K,
                'fx': fx,
                'fy': fy,
                'cx': cx,
                'cy': cy,
                'fov_degrees': math.degrees(fov_rad)
            },
            'extrinsic': {
                'T_cw': T_cw,  # Camera to World
                'T_wc': T_wc,  # World to Camera
                'R': R,
                't': t
            },
            'matrices': {
                'view_matrix': view_matrix,
                'projection_matrix': projection_matrix
            },
            'camera_info': {
                'location': list(cam_obj.location),
                'rotation_euler': list(cam_obj.rotation_euler),
                'lens_angle_degrees': math.degrees(cam_data.angle),
                'clip_start': near,
                'clip_end': far,
                'shift_x': cam_data.shift_x,
                'shift_y': cam_data.shift_y
            }
        }

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
