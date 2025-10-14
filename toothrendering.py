import bpy
import os
import json
import mathutils
import math
import subprocess
import sys
import time


# 설정 변수
MAX_CASES = 1  # 처리할 최대 케이스 수
Reverses = False  # 폴더 순서 역순 여부
Sequence = True # true : 카메라 각도를 연속으로, false : 기존 10개 카메라 각도 사용용 
# top -> left -> bottom 3개의 기존 카메라 각도를 키프레임으로 사용
# top -> left 15장, left -> bottom 15장, 총 30장의 이미지를 저장함.
# 전체 사진들을 순서대로 이어서 보면 동영상처럼 카메라가 orbital 회전하는것처럼 구현해야함

# 렌더링 타입별 활성화 설정
RENDER_LIT = True  # 라이팅 머티리얼 (Cycles)
RENDER_UNLIT = True  # semantic map (EEVEE)
RENDER_MATT = True  # 매트 머티리얼 (EEVEE)
RENDER_DEPTH = True  # 뎁스 맵 (EEVEE)
RENDER_NORMAL = True  # 노멀 맵 (EEVEE)
RENDER_CURVATURE = True  # 곡률 맵 (EEVEE)

# Windows에서 별도 콘솔창 띄우기
if sys.platform == "win32":
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # 콘솔 할당
        kernel32.AllocConsole()

        # 콘솔 창 제목 설정
        kernel32.SetConsoleTitleW("Blender Tooth Rendering Progress")

        # 콘솔 창 크기 조정
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.SetWindowPos(hwnd, 0, 100, 100, 800, 600, 0x0040)
    except:
        pass


class OT_SelectFolderAndColorize(bpy.types.Operator):
    bl_idname = "object.select_folder_and_colorize"
    bl_label = "Select Folder and Apply Gingiva/Tooth Materials"
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

        # GPU 렌더링 설정 (Cycles)
        scene.cycles.device = "GPU"
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True

        # GPU 메모리 최적화 (RTX 4070 최적화)
        scene.cycles.tile_size = 512  # RTX 4070에 최적화된 타일 크기
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.01
        scene.cycles.adaptive_min_samples = 64
        scene.cycles.max_bounces = 12  # 반사 횟수 증가로 GPU 활용도 향상
        scene.cycles.caustics_reflective = True  # 반사 카우스틱 활성화
        scene.cycles.caustics_refractive = True  # 굴절 카우스틱 활성화

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

        # === 잇몸 머티리얼 (AO 노드 적용) ===
        mat_gum = bpy.data.materials.get("Gingiva_mat") or bpy.data.materials.new(
            "Gingiva_mat"
        )
        mat_gum.use_nodes = True
        nodes_gum = mat_gum.node_tree.nodes
        links_gum = mat_gum.node_tree.links
        nodes_gum.clear()

        # Principled BSDF 노드
        principled_gum = nodes_gum.new(type="ShaderNodeBsdfPrincipled")
        principled_gum.location = (0, 0)

        # 안전한 입력 설정 (버전 호환성)
        try:
            principled_gum.inputs["Base Color"].default_value = (
                1.0,
                0.196,
                0.282,
                1.0,
            )  # #FF3248FF
        except KeyError:
            try:
                principled_gum.inputs["Color"].default_value = (
                    1.0,
                    0.196,
                    0.282,
                    1.0,
                )  # #FF3248FF
            except KeyError:
                principled_gum.inputs[0].default_value = (
                    1.0,
                    0.196,
                    0.282,
                    1.0,
                )  # #FF3248FF

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
        mix_node_gum.inputs[2].default_value = (
            1.0,
            0.1177,
            0.1518,
            1.0,
        )  # color2

        # Material Output 노드
        output_gum = nodes_gum.new(type="ShaderNodeOutputMaterial")
        output_gum.location = (200, 0)

        # 노드 연결 (안전한 연결)
        try:
            # AO 노드를 Mix 노드의 Factor(inputs[0])에 연결하여 AO 강도로 사용
            links_gum.new(ao_node_gum.outputs["AO"], mix_node_gum.inputs[0])
            links_gum.new(mix_node_gum.outputs[0], principled_gum.inputs["Base Color"])
            links_gum.new(principled_gum.outputs["BSDF"], output_gum.inputs["Surface"])
        except KeyError:
            # 대안 연결 방법
            links_gum.new(ao_node_gum.outputs[0], mix_node_gum.inputs[0])
            links_gum.new(mix_node_gum.outputs[0], principled_gum.inputs[0])
            links_gum.new(principled_gum.outputs[0], output_gum.inputs[0])

        # === 치아 머티리얼 (이미지 구조대로 수정) ===
        mat_tooth = bpy.data.materials.get("Teeth_mat") or bpy.data.materials.new(
            "Teeth_mat"
        )
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
            principled.inputs[7].default_value = 0.1  # Roughness는 보통 7번 인덱스

        try:
            principled.inputs["Metallic"].default_value = 0.0
        except KeyError:
            principled.inputs[6].default_value = 0.0  # Metallic은 보통 6번 인덱스

        # Coat 속성 추가 (촉촉한 느낌) - 안전한 설정
        try:
            principled.inputs["Coat Weight"].default_value = 0.8
            principled.inputs["Coat Roughness"].default_value = 0.05
            principled.inputs["Coat IOR"].default_value = 1.5
        except KeyError:
            # Coat 속성이 없는 경우 기본값으로 설정
            pass

        # Subsurface Scattering 속성 추가 (치아 내부 빛 산란 효과)
        principled.inputs["Subsurface Weight"].default_value = 1.0  # SSS 강도 (0.0~1.0)
        principled.inputs["Subsurface Radius"].default_value = (
            0.1,
            0.1,
            0.1,
        )  # RGB 산란 반경
        principled.inputs["Subsurface Scale"].default_value = 10.0  # 스케일
        principled.inputs["Subsurface Anisotropy"].default_value = 0.0  # 이방성
        principled.inputs["Transmission Weight"].default_value = 0.1  # 투명도 (0.0~1.0)

        # === 첫 번째 AO 노드 (치아용) ===
        ao_node_tooth = nodes_tooth.new(type="ShaderNodeAmbientOcclusion")
        ao_node_tooth.location = (-600, 100)
        ao_node_tooth.inputs["Distance"].default_value = 2000.0
        ao_node_tooth.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)

        # === 두 번째 AO 노드 (치아용) ===
        ao_node_gum = nodes_tooth.new(type="ShaderNodeAmbientOcclusion")
        ao_node_gum.location = (-600, -100)
        ao_node_gum.inputs["Distance"].default_value = 20000.0
        ao_node_gum.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)

        # === 첫 번째 Power 노드 (치아 AO용) ===
        power_node_tooth = nodes_tooth.new(type="ShaderNodeMath")
        power_node_tooth.location = (-450, 100)
        power_node_tooth.operation = "POWER"
        power_node_tooth.inputs[1].default_value = 3.0  # 지수값

        # === 두 번째 Power 노드 (잇몸 AO용) ===
        power_node_gum = nodes_tooth.new(type="ShaderNodeMath")
        power_node_gum.location = (-450, -100)
        power_node_gum.operation = "POWER"
        power_node_gum.inputs[1].default_value = 10.0  # 지수값

        # === 첫 번째 Mix 노드 (치아용 - Multiply) ===
        mix_node_tooth = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_tooth.location = (-300, 100)
        mix_node_tooth.blend_type = "MULTIPLY"
        mix_node_tooth.inputs[0].default_value = 0.3  # AO 강도
        mix_node_tooth.inputs[1].default_value = (
            1.0,
            0.890,
            0.498,
            1.0,
        )  # #FFE37FFF (color1)
        mix_node_tooth.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)  # 흰색 (color2)

        # === 두 번째 Mix 노드 (잇몸용 - Mix) ===
        mix_node_gum = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_gum.location = (-300, -100)
        mix_node_gum.blend_type = "MIX"
        mix_node_gum.inputs[0].default_value = 0.8  # AO 강도
        mix_node_gum.inputs[1].default_value = (1.0, 1.0, 0.0, 1.0)  # 노란색 (color1)
        mix_node_gum.inputs[2].default_value = (1.0, 1.0, 1.0, 1.0)  # 흰색 (color2)

        # === 세 번째 Mix 노드 (추가) ===
        mix_node_extra = nodes_tooth.new(type="ShaderNodeMixRGB")
        mix_node_extra.location = (-150, -100)
        mix_node_extra.blend_type = "MIX"
        mix_node_extra.inputs[0].default_value = 0.5  # Factor
        mix_node_extra.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)  # 흰색 (color1)
        mix_node_extra.inputs[2].default_value = (1.0, 0.8, 0.31, 1.0)  # color2

        # === 메인 Mix 노드 (Color 블렌드) ===
        main_mix_node = nodes_tooth.new(type="ShaderNodeMixRGB")
        main_mix_node.location = (0, 0)
        main_mix_node.blend_type = "COLOR"
        main_mix_node.inputs[0].default_value = 0.5  # Factor

        # Material Output 노드
        output = nodes_tooth.new(type="ShaderNodeOutputMaterial")
        output.location = (200, 0)

        # 노드 연결 (안전한 연결)
        try:
            # 첫 번째 브랜치 (치아)
            links_tooth.new(ao_node_tooth.outputs["AO"], power_node_tooth.inputs[0])
            links_tooth.new(
                power_node_tooth.outputs[0], mix_node_tooth.inputs[1]
            )  # Color1에 Power 출력 연결
            links_tooth.new(
                mix_node_tooth.outputs[0], main_mix_node.inputs[1]
            )  # A 입력

            # 두 번째 브랜치 (잇몸)
            links_tooth.new(ao_node_gum.outputs["AO"], power_node_gum.inputs[0])
            links_tooth.new(power_node_gum.outputs[0], mix_node_gum.inputs[0])
            links_tooth.new(mix_node_gum.outputs[0], mix_node_extra.inputs[0])
            links_tooth.new(
                mix_node_extra.outputs[0], main_mix_node.inputs[2]
            )  # B 입력

            # 메인 연결
            links_tooth.new(main_mix_node.outputs[0], principled.inputs["Base Color"])
            links_tooth.new(principled.outputs["BSDF"], output.inputs["Surface"])
        except KeyError:
            # 대안 연결 방법
            links_tooth.new(ao_node_tooth.outputs[0], power_node_tooth.inputs[0])
            links_tooth.new(
                power_node_tooth.outputs[0], mix_node_tooth.inputs[1]
            )  # Color1에 Power 출력 연결
            links_tooth.new(mix_node_tooth.outputs[0], main_mix_node.inputs[1])

            links_tooth.new(ao_node_gum.outputs[0], power_node_gum.inputs[0])
            links_tooth.new(power_node_gum.outputs[0], mix_node_gum.inputs[0])
            links_tooth.new(mix_node_gum.outputs[0], mix_node_extra.inputs[0])
            links_tooth.new(mix_node_extra.outputs[0], main_mix_node.inputs[2])

            links_tooth.new(main_mix_node.outputs[0], principled.inputs[0])
            links_tooth.new(principled.outputs[0], output.inputs[0])
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
            links_gum.new(
                emission_gum.outputs["Emission"], output_gum.inputs["Surface"]
            )
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
            links_tooth.new(
                emission_tooth.outputs["Emission"], output_tooth.inputs["Surface"]
            )

        # === Matt 머티리얼 (기본 흰색) ===
        mat_gum_matt = bpy.data.materials.get("Gingiva_matt")
        if not mat_gum_matt:
            mat_gum_matt = bpy.data.materials.new("Gingiva_matt")
            mat_gum_matt.use_nodes = True
            nodes_gum_matt = mat_gum_matt.node_tree.nodes
            links_gum_matt = mat_gum_matt.node_tree.links
            nodes_gum_matt.clear()

            # Principled BSDF 노드
            principled_gum_matt = nodes_gum_matt.new(type="ShaderNodeBsdfPrincipled")
            principled_gum_matt.location = (0, 0)

            # 기본 흰색 설정
            try:
                principled_gum_matt.inputs["Base Color"].default_value = (
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                )
            except KeyError:
                try:
                    principled_gum_matt.inputs["Color"].default_value = (
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                    )
                except KeyError:
                    principled_gum_matt.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

            try:
                principled_gum_matt.inputs["Roughness"].default_value = 0.5
            except KeyError:
                principled_gum_matt.inputs[7].default_value = 0.5

            # Material Output 노드
            output_gum_matt = nodes_gum_matt.new(type="ShaderNodeOutputMaterial")
            output_gum_matt.location = (200, 0)

            # 노드 연결
            try:
                links_gum_matt.new(
                    principled_gum_matt.outputs["BSDF"],
                    output_gum_matt.inputs["Surface"],
                )
            except KeyError:
                links_gum_matt.new(
                    principled_gum_matt.outputs[0], output_gum_matt.inputs[0]
                )

        mat_tooth_matt = bpy.data.materials.get("Tooth_matt")
        if not mat_tooth_matt:
            mat_tooth_matt = bpy.data.materials.new("Tooth_matt")
            mat_tooth_matt.use_nodes = True
            nodes_tooth_matt = mat_tooth_matt.node_tree.nodes
            links_tooth_matt = mat_tooth_matt.node_tree.links
            nodes_tooth_matt.clear()

            # Principled BSDF 노드
            principled_tooth_matt = nodes_tooth_matt.new(
                type="ShaderNodeBsdfPrincipled"
            )
            principled_tooth_matt.location = (0, 0)

            # 기본 흰색 설정
            try:
                principled_tooth_matt.inputs["Base Color"].default_value = (
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                )
            except KeyError:
                try:
                    principled_tooth_matt.inputs["Color"].default_value = (
                        1.0,
                        1.0,
                        1.0,
                        1.0,
                    )
                except KeyError:
                    principled_tooth_matt.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)

            try:
                principled_tooth_matt.inputs["Roughness"].default_value = 0.5
            except KeyError:
                principled_tooth_matt.inputs[7].default_value = 0.5

            # Material Output 노드
            output_tooth_matt = nodes_tooth_matt.new(type="ShaderNodeOutputMaterial")
            output_tooth_matt.location = (200, 0)

            # 노드 연결
            try:
                links_tooth_matt.new(
                    principled_tooth_matt.outputs["BSDF"],
                    output_tooth_matt.inputs["Surface"],
                )
            except KeyError:
                links_tooth_matt.new(
                    principled_tooth_matt.outputs[0], output_tooth_matt.inputs[0]
                )

        # === Curvature 머티리얼 (Cycles Geometry Pointiness 기반) ===
        mat_curvature = bpy.data.materials.get("Curvature_mat")
        if not mat_curvature:
            mat_curvature = bpy.data.materials.new("Curvature_mat")
            mat_curvature.use_nodes = True
            nodes_curv = mat_curvature.node_tree.nodes
            links_curv = mat_curvature.node_tree.links
            nodes_curv.clear()

            geom = nodes_curv.new(type="ShaderNodeNewGeometry")
            geom.location = (-400, 0)

            # 대비 강화를 위한 Power 노드 추가 (Pointiness^2.5)
            power_curv = nodes_curv.new(type="ShaderNodeMath")
            power_curv.location = (-300, 0)
            power_curv.operation = "POWER"
            power_curv.inputs[1].default_value = 2.9

            ramp = nodes_curv.new(type="ShaderNodeValToRGB")
            ramp.location = (-200, 0)
            # 기본 커브 설정 (메시 밀도에 따라 조절 필요)
            try:
                # 더 강한 대비를 위해 구간을 좁힘
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

        # === 하위 폴더(케이스) 자동 순회 (최대 10개, tqdm 진행률 표시) ===
        parent_folder = os.path.basename(os.path.normpath(self.folder_path))
        case_folders = [
            f
            for f in sorted(os.listdir(self.folder_path), reverse=Reverses)
            if os.path.isdir(os.path.join(self.folder_path, f))
        ]
        case_folders = case_folders[:MAX_CASES]  # 최대 케이스 수만큼만

        total = len(case_folders)
        total_views = len(camera_positions)

        # 활성화된 렌더링 타입 수 계산
        active_render_types = sum(
            [
                RENDER_LIT,
                RENDER_UNLIT,
                RENDER_MATT,
                RENDER_DEPTH,
                RENDER_NORMAL,
                RENDER_CURVATURE,
            ]
        )
        total_renders = total * total_views * active_render_types

        start_time = time.time()
        print(f"Total renders: {total_renders}")

        for idx, selected_folder in enumerate(case_folders, 1):
            case_start_time = time.time()
            print(f"[{idx}/{total}] Processing: {selected_folder}")
            case_path = os.path.join(self.folder_path, selected_folder)
            if not os.path.isdir(case_path):
                continue
            # 폴더 내 obj, json 자동 탐색
            obj_file = None
            json_file = None
            for f in os.listdir(case_path):
                if f.endswith(".obj"):
                    obj_file = os.path.join(case_path, f)
                elif f.endswith(".json"):
                    json_file = os.path.join(case_path, f)
            if not obj_file or not json_file:
                self.report(
                    {"WARNING"}, f"{case_path}: OBJ 또는 JSON 파일을 찾을 수 없습니다."
                )
                continue

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
            mesh.materials.append(mat_gum_unlit)
            mesh.materials.append(mat_tooth_unlit)

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
            file_prefix = f"{parent_folder}_{selected_folder}"
            
            # 카메라 루프
            if Sequence:
                # Sequence 모드: top->left->bottom 보간으로 30장 생성
                total_sequence_frames = 30
                frames_per_segment = 15  # top->left: 15장, left->bottom: 15장
                
                for frame_idx in range(total_sequence_frames):
                    # 프레임 인덱스에 따라 보간 계산
                    if frame_idx < frames_per_segment:
                        # top -> left 보간 (0~14)
                        t = frame_idx / (frames_per_segment - 1)
                        start_pos = camera_positions[0][1]  # top
                        end_pos = camera_positions[1][1]    # left
                        cam_pos = start_pos.lerp(end_pos, t)
                        view_name = f"seq_{frame_idx:02d}_top_to_left"
                    else:
                        # left -> bottom 보간 (15~29)
                        t = (frame_idx - frames_per_segment) / (frames_per_segment - 1)
                        start_pos = camera_positions[1][1]  # left
                        end_pos = camera_positions[2][1]    # bottom
                        cam_pos = start_pos.lerp(end_pos, t)
                        view_name = f"seq_{frame_idx:02d}_left_to_bottom"
                    
                    # 카메라 생성 및 렌더링
                    cam_data = bpy.data.cameras.new(view_name + "_cam")
                    cam_obj = bpy.data.objects.new(view_name + "_cam", cam_data)
                    bpy.context.collection.objects.link(cam_obj)
                    cam_obj.location = cam_pos
                    direction = target - cam_pos
                    rot_quat = direction.to_track_quat("-Z", "Y")
                    cam_obj.rotation_euler = rot_quat.to_euler()
                    bpy.context.scene.camera = cam_obj
                    cam_data.angle = math.radians(60)
                    
                    # directional light 생성
                    light_data = bpy.data.lights.new(view_name + "_sun", type="SUN")
                    light_data.energy = 5
                    light_data.use_shadow = True
                    light_obj = bpy.data.objects.new(view_name + "_sun", light_data)
                    bpy.context.collection.objects.link(light_obj)
                    light_obj.parent = cam_obj
                    
                    # 렌더링 카운터 초기화
                    render_count = 0
                    
                    # 각 렌더링 타입별로 렌더링 (기존 로직 재사용)
                    render_count = self._render_all_types(scene, mesh, mat_gum, mat_tooth, mat_gum_unlit, mat_tooth_unlit, 
                                         mat_gum_matt, mat_tooth_matt, mat_curvature, file_prefix, 
                                         view_name, lit_dir, unlit_dir, matt_dir, depth_dir, normal_dir, 
                                         curvature_dir, light_data, cam_obj, obj)
                    
                    # 진행률 출력
                    elapsed_time = time.time() - start_time
                    avg_time_per_render = elapsed_time / (frame_idx + 1)
                    remaining_frames = total_sequence_frames - (frame_idx + 1)
                    estimated_remaining_time = remaining_frames * avg_time_per_render
                    
                    def format_time(seconds):
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        if hours > 0:
                            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                        else:
                            return f"{minutes:02d}:{secs:02d}"
                    
                    print(f"  [{idx}/{total}] Model {idx} - Frame {frame_idx+1}/{total_sequence_frames}: {view_name} | "
                          f"Elapsed: {format_time(elapsed_time)} | ETA: {format_time(estimated_remaining_time)}")
                    
                    # 카메라와 라이트 정리
                    bpy.data.objects.remove(cam_obj, do_unlink=True)
                    bpy.data.objects.remove(light_obj, do_unlink=True)
                    
            else:
                # 기존 모드: 10개 카메라 각도 사용
                total_views = len(camera_positions)
                for i, (name, cam_pos) in enumerate(camera_positions):
                    # 카메라 생성
                    cam_data = bpy.data.cameras.new(name + "_cam")
                    cam_obj = bpy.data.objects.new(name + "_cam", cam_data)
                    bpy.context.collection.objects.link(cam_obj)
                    cam_obj.location = cam_pos
                    direction = target - cam_pos
                    rot_quat = direction.to_track_quat("-Z", "Y")
                    cam_obj.rotation_euler = rot_quat.to_euler()
                    bpy.context.scene.camera = cam_obj
                    cam_data.angle = math.radians(60)
                    # directional light 생성
                    light_data = bpy.data.lights.new(name + "_sun", type="SUN")
                    light_data.energy = 5
                    light_data.use_shadow = True
                    light_obj = bpy.data.objects.new(name + "_sun", light_data)
                    bpy.context.collection.objects.link(light_obj)
                    light_obj.parent = cam_obj

                    # 렌더링 카운터 초기화
                    render_count = 0

                    # 각 렌더링 타입별로 렌더링
                    render_count = self._render_all_types(scene, mesh, mat_gum, mat_tooth, mat_gum_unlit, mat_tooth_unlit, 
                                         mat_gum_matt, mat_tooth_matt, mat_curvature, file_prefix, 
                                         name, lit_dir, unlit_dir, matt_dir, depth_dir, normal_dir, 
                                         curvature_dir, light_data, cam_obj, obj)

                    # 진행률 및 시간 정보 출력 (활성화된 렌더링 타입 기준)
                    current_render = (
                        (idx - 1)
                        * total_views
                        * active_render_types  # 이전 케이스까지 완료 수
                        + i * active_render_types  # 현재 케이스의 이전 뷰 완료 수
                        + render_count  # 현재 뷰에서 완료한 렌더 수
                    )
                    elapsed_time = time.time() - start_time
                    avg_time_per_render = elapsed_time / current_render
                    remaining_renders = total_renders - current_render
                    estimated_remaining_time = remaining_renders * avg_time_per_render

                    # 시간을 시:분:초 형식으로 변환
                    def format_time(seconds):
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        if hours > 0:
                            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                        else:
                            return f"{minutes:02d}:{secs:02d}"

                    print(
                        f"  [{idx}/{total}] Model {idx} - View {i+1}/{total_views}: {name} | "
                        f"Elapsed: {format_time(elapsed_time)} | ETA: {format_time(estimated_remaining_time)}\n"
                    )

                    # 마지막 반복이 아닌 경우에만 조명도 삭제
                    if i < len(camera_positions) - 1:
                        bpy.data.objects.remove(cam_obj, do_unlink=True)
                        bpy.data.objects.remove(light_obj, do_unlink=True)

        return {"FINISHED"}

    def _render_all_types(self, scene, mesh, mat_gum, mat_tooth, mat_gum_unlit, mat_tooth_unlit, 
                         mat_gum_matt, mat_tooth_matt, mat_curvature, file_prefix, 
                         view_name, lit_dir, unlit_dir, matt_dir, depth_dir, normal_dir, 
                         curvature_dir, light_data, cam_obj, obj):
        """모든 렌더링 타입을 순차적으로 실행"""
        render_count = 0
        
        # === unlit 머티리얼 적용 (EEVEE) ===
        if RENDER_UNLIT:
            # 컴포지터 비활성화 (일반 렌더링)
            scene.use_nodes = False

            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
            mesh.materials[0] = mat_gum_unlit
            mesh.materials[1] = mat_tooth_unlit
            unlit_path = os.path.join(unlit_dir, f"{file_prefix}_{view_name}.png")
            bpy.context.scene.render.filepath = unlit_path
            bpy.ops.render.render(write_still=True)
            render_count += 1

        # === matt 머티리얼 적용 (EEVEE - 기본 흰색) ===
        if RENDER_MATT:
            # 컴포지터 비활성화 (일반 렌더링)
            scene.use_nodes = False

            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
            # matt에서는 그림자 제거
            _saved_shadow = light_data.use_shadow
            light_data.use_shadow = False
            mesh.materials[0] = mat_gum_matt
            mesh.materials[1] = mat_tooth_matt
            matt_path = os.path.join(matt_dir, f"{file_prefix}_{view_name}.png")
            bpy.context.scene.render.filepath = matt_path
            bpy.ops.render.render(write_still=True)
            # 원래 그림자 설정 복구 (다음 렌더에 영향 방지)
            light_data.use_shadow = _saved_shadow
            render_count += 1

        # === 라이팅 머티리얼 적용 (Cycles - GPU Path Tracing) ===
        if RENDER_LIT:
            # 컴포지터 비활성화 (일반 렌더링)
            scene.use_nodes = False

            bpy.context.scene.render.engine = "CYCLES"
            # GPU 렌더링 설정이 이미 위에서 적용됨

            mesh.materials[0] = mat_gum
            mesh.materials[1] = mat_tooth
            lit_path = os.path.join(lit_dir, f"{file_prefix}_{view_name}.png")
            bpy.context.scene.render.filepath = lit_path
            bpy.ops.render.render(write_still=True)
            render_count += 1

        # === depth 맵 (EEVEE + Z Pass Normalize, 스크린 공간 자동 정규화) ===
        if RENDER_DEPTH:
            # 화면 기준(카메라 공간) 깊이 최소/최대 계산: 실제 메시 모든 정점 사용
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

            # 뷰에 맞춰 카메라 클리핑 범위를 메시 범위로 세팅 (배경 무한값 영향 최소화)
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

            # 컴포지터: Depth -> Normalize -> Composite (근=검정, 원=흰색)
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

            depth_path = os.path.join(depth_dir, f"{file_prefix}_{view_name}.png")
            bpy.context.scene.render.filepath = depth_path
            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
            bpy.ops.render.render(write_still=True, use_viewport=False)

            # 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
            scene.view_settings.view_transform = prev_view_transform
            scene.use_nodes = prev_use_nodes

            render_count += 1

        # === normal 맵 (EEVEE + Normal Pass) ===
        if RENDER_NORMAL:
            # EEVEE 엔진으로 설정
            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"

            # 라이팅 효과 완전히 제거 (unlit처럼)
            _saved_shadow = light_data.use_shadow
            light_data.use_shadow = False
            _saved_energy = light_data.energy
            light_data.energy = 0.0  # 라이트 완전히 끔

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

            # Math 노드들로 노멀을 0-1 범위로 변환 (더 안전한 방법)
            # X 채널 처리
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

            normal_path = os.path.join(normal_dir, f"{file_prefix}_{view_name}.png")
            bpy.context.scene.render.filepath = normal_path
            bpy.ops.render.render(write_still=True, use_viewport=False)

            # 설정 복구
            img_settings.file_format = prev_format
            img_settings.color_mode = prev_color_mode
            img_settings.color_depth = prev_color_depth
            scene.view_settings.view_transform = prev_view_transform
            scene.use_nodes = prev_use_nodes

            # 라이팅 설정 복구
            light_data.use_shadow = _saved_shadow
            light_data.energy = _saved_energy

            render_count += 1

        # === curvature 맵 (Cycles + Geometry Pointiness) ===
        if RENDER_CURVATURE:
            # 컴포지터 비활성화 (일반 렌더링)
            scene.use_nodes = False

            # Pointiness는 Cycles에서 동작
            bpy.context.scene.render.engine = "CYCLES"

            # 머티리얼 모두 커브처로 적용
            mesh.materials[0] = mat_curvature
            if len(mesh.materials) > 1:
                mesh.materials[1] = mat_curvature

            # 표준 보기 변환으로 저장 (색 왜곡 방지)
            prev_view_transform = scene.view_settings.view_transform
            scene.view_settings.view_transform = "Standard"

            curvature_path = os.path.join(
                curvature_dir, f"{file_prefix}_{view_name}.png"
            )
            bpy.context.scene.render.filepath = curvature_path
            bpy.ops.render.render(write_still=True)

            # 복구
            scene.view_settings.view_transform = prev_view_transform
            render_count += 1

        return render_count

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
#
