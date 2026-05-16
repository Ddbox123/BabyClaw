# -*- coding: utf-8 -*-
"""
ASCII 艺术库 - 多角色形象系统

提供多种可爱的 ASCII Art 角色形象，用于 CLI 界面装饰。
支持 lobster(龙虾), shrimp(小虾米), crab(小螃蟹), cat(猫猫), chick(小鸡)
"""

from __future__ import annotations

from typing import Dict, Type


def _mirror_ascii_art(art: str) -> str:
    lines = art.strip("\n").splitlines()
    translation = str.maketrans(r"/\()<>{}[]", r"\/)(><}{][")
    mirrored = []
    for line in lines:
        mirrored.append(line[::-1].translate(translation))
    return "\n".join(mirrored)


def _generic_pose_from_status(provider_cls, pose: str, direction: str = "right", frame_index: int = 0) -> str:
    pose_to_status = {
        "idle": "happy",
        "walk": "working",
        "turn": "surprised",
        "think": "thinking",
        "sleep": "sleeping",
        "success": "success",
        "sad": "sad",
        "confused": "surprised",
        "tired": "sleeping",
    }
    status = pose_to_status.get(pose, "happy")
    art = provider_cls.get_status_art(status).strip("\n")
    if pose == "walk" and frame_index % 2 == 1:
        art = art.replace("..'", ". .'").replace("zzZ", "z z")
    if pose == "turn":
        art = provider_cls.get_status_art("surprised").strip("\n")
    if direction == "left":
        art = _mirror_ascii_art(art)
    return art


def _make_lobster_sprite(
    eyes: str = "o o",
    mouth: str = "~",
    leg_variant: int = 0,
    claw_variant: int = 0,
    topper: str = "",
) -> str:
    claw_sets = [
        (
            "      __     __",
            "  ___/  \\___/  \\___",
            " /___    ___    ___\\",
        ),
        (
            "      __     __",
            "  ___/  \\___/  \\___",
            " /___    _^_    ___\\",
        ),
        (
            "      __     __",
            "  ___/  \\___/  \\___",
            " /___    _!_    ___\\",
        ),
    ]
    top_claw, mid_claw, low_claw = claw_sets[claw_variant % len(claw_sets)]

    belly_sets = [
        (
            "   \\_\\  /| |\\  /_/",
            "    \\_\\/ | | \\/_/",
            "     /_/ |_| \\_\\",
            "      /_/   \\_\\",
        ),
        (
            "   \\_\\  /|_|\\  /_/",
            "    \\_\\/ |_| \\/_/",
            "     /_/ |_| \\_\\",
            "      /_/   \\_\\",
        ),
    ]
    upper_belly, mid_belly, lower_belly, tail = belly_sets[leg_variant % len(belly_sets)]

    face = [
        "      .-^^-.",
        f"    .' {eyes} '.",
        "    |   /\\   |",
        f"    |  ({mouth})  |",
        "     \\ .__. /",
    ]

    lines = [
        top_claw,
        mid_claw,
        low_claw,
        *face,
        upper_belly,
        mid_belly,
        lower_belly,
        tail,
    ]
    if topper:
        lines.insert(0, topper)
    return "\n".join(lines) + "\n"


# ==================== 龙虾 ASCII Art ====================
class LobsterASCII:
    """龙虾 ASCII Art 艺术库"""

    POSE_ART = {
        ("idle", "right"): [
            _make_lobster_sprite("o o", "~", leg_variant=1),
        ],
        ("idle", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("o o", "~", leg_variant=1)),
        ],
        ("walk", "right"): [
            _make_lobster_sprite("o o", "^", leg_variant=0, claw_variant=0),
            _make_lobster_sprite("o o", "^", leg_variant=1, claw_variant=1),
        ],
        ("walk", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("o o", "^", leg_variant=0, claw_variant=0)),
            _mirror_ascii_art(_make_lobster_sprite("o o", "^", leg_variant=1, claw_variant=1)),
        ],
        ("turn", "right"): [
            _make_lobster_sprite("o O", "!", leg_variant=0, claw_variant=2),
            _make_lobster_sprite("o o", "~", leg_variant=1, claw_variant=1),
        ],
        ("turn", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("o O", "!", leg_variant=0, claw_variant=2)),
            _mirror_ascii_art(_make_lobster_sprite("o o", "~", leg_variant=1, claw_variant=1)),
        ],
        ("think", "right"): [
            _make_lobster_sprite("? ?", ".", leg_variant=1),
        ],
        ("think", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("? ?", ".", leg_variant=1)),
        ],
        ("sleep", "right"): [
            _make_lobster_sprite("- -", "_", leg_variant=0, topper="   zZ"),
        ],
        ("sleep", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("- -", "_", leg_variant=0, topper="   zZ")),
        ],
        ("success", "right"): [
            _make_lobster_sprite("^ ^", "v", leg_variant=1, claw_variant=1),
        ],
        ("success", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("^ ^", "v", leg_variant=1, claw_variant=1)),
        ],
        ("sad", "right"): [
            _make_lobster_sprite("; ;", ".", leg_variant=0),
        ],
        ("sad", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("; ;", ".", leg_variant=0)),
        ],
        ("confused", "right"): [
            _make_lobster_sprite("@ ?", "?", leg_variant=0, claw_variant=2),
        ],
        ("confused", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("@ ?", "?", leg_variant=0, claw_variant=2)),
        ],
        ("tired", "right"): [
            _make_lobster_sprite("- -", "_", leg_variant=0),
        ],
        ("tired", "left"): [
            _mirror_ascii_art(_make_lobster_sprite("- -", "_", leg_variant=0)),
        ],
    }

    HAPPY = r"""
      __
  ___( o)>
  \ <_. )
   `---'
   /|_|\
  /_/ \_\
"""

    THINKING = r"""
      __
  ___( ?)>
  \ <_. )
   `-?-'
   /|_|\
  /_/ \_\
"""

    WORKING = r"""
      __
  ___( *}>
  \ <_. )
   `-~-'
   /|_|\
  /_/ \_\
"""

    SLEEPING = r"""
      __
  ___( -)>
  \ <_. )
   `-z-'
   /|_|\
  /_/ \_\
"""

    SURPRISED = r"""
      __
  ___( O)>
  \ <_. )
   `-!-'
   /|_|\
  /_/ \_\
"""

    SUCCESS = r"""
      __
  ___( ^)>
  \ <_o )
   `-v-'
   /|_|\
  /_/ \_\
"""

    SAD = r"""
      __
  ___( ;)>
  \ <_. )
   `-.-'
   /|_|\
  /_/ \_\
"""

    LOVE = r"""
      __
  ___(<3)>
  \ <3. )
   `---'
   /|_|\
  /_/ \_\
"""

    TINY = r"""
 (\ /)
 (^o^)
"""

    DIVIDER = "─" * 70

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": ("idle", "right"),
            "thinking": ("think", "right"),
            "working": ("walk", "right"),
            "sleeping": ("sleep", "right"),
            "surprised": ("confused", "right"),
            "success": ("success", "right"),
            "sad": ("sad", "right"),
            "error": ("sad", "right"),
            "love": ("success", "right"),
        }
        pose, direction = status_map.get(status.lower(), ("idle", "right"))
        return cls.get_pose_art(pose=pose, direction=direction, frame_index=0)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        sprites = cls.POSE_ART.get((pose, direction))
        if not sprites:
            sprites = cls.POSE_ART.get(("idle", direction)) or cls.POSE_ART[("idle", "right")]
        index = frame_index % len(sprites)
        return sprites[index]

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        """生成 Banner"""
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小虾米 ASCII Art ====================
class ShrimpASCII:
    """小虾米 ASCII Art - Q萌跳跃版"""

    HAPPY = r"""
     /\..{
    /  \  )~
   |    \( (
    \    ) )
     \  ( (
      \__|__\
       \ `  /
       /`-'/
      '..'
"""

    THINKING = r"""
     /\..{
    /  \  )~
   |    \( (
    \    ) )
     \  ( (
      \__|__\
       \.-./
        /V\
       / | \
"""

    WORKING = r"""
     /\..{
    /  \  )~
   |    \( *_*) 
    \    ) )
     \  ( (
      \__|__\
       \***/
       /`-`\
      '..'
"""

    SLEEPING = r"""
     /\..{
    /  \  )~
   |    \( - ) 
    \    ) )
     \  ( (
      \__|__\
       \   /
       /`-`\
      '..'
     zzZZ
"""

    SURPRISED = r"""
     /\..{
    /  \  )~
   |    \( O_O) 
    \    ) )
     \  ( (
      \__|__\
       \ ! /
       /`-'/
      '..'
"""

    SUCCESS = r"""
     /\..{
    /  \  )~
   |    \( ^o^) 
    \    ) )
     \  ( (
      \__|__\
       \ * /
       /`-'\
      '..' *
"""

    SAD = r"""
     /\..{
    /  \  )~
   |    \( T_T) 
    \    ) )
     \  ( (
      \__|__\
       \ ` /
       /`-`\
      '..'
"""

    LOVE = r"""
     /\..{
    /  \  )~
   |    \( <3<3) 
    \    ) )
     \  ( (
      \__|__\
       \ * /
       /`-'\
      '..'
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小螃蟹 ASCII Art ====================
class CrabASCII:
    """小螃蟹 ASCII Art - 简洁卡通版"""

    HAPPY = r"""
    ,----,
   /  o o  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    THINKING = r"""
    ,----,
   /  ? ?  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    WORKING = r"""
    ,----,
   /  * *  \
  |   ~~   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    SLEEPING = r"""
    ,----,
   /  - -  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
    zzZZ
"""

    SURPRISED = r"""
    ,----,
   /  O O  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    SUCCESS = r"""
    ,----,
   /  ^ ^  \
  |   \/   |
  |  (  )  |
   \  ||  /
    '----' *
   /|    |\
  / |    | \
"""

    SAD = r"""
    ,----,
   /  x x  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    LOVE = r"""
    ,----,
   /  < >  \
  |   \/   |
  |  (  )  |
   \  ||  /
    '----' *
   /|    |\
  / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 猫猫 ASCII Art ====================
class CatASCII:
    """猫猫 ASCII Art - 可爱猫猫机器人版"""

    HAPPY = r"""
   /\_____/\
  /  o   o  \
 ( ==  ^  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    THINKING = r"""
   /\_____/\
  /  o   o  \
 ( ==  ?  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    WORKING = r"""
   /\_____/\
  /  *   *  \
 ( ==  <  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    SLEEPING = r"""
   /\_____/\
  /  -   -  \
 ( ==  -  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
    zzZ
"""

    SURPRISED = r"""
   /\_____/\
  /  O   O  \
 ( ==  !  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    SUCCESS = r"""
   /\_____/\
  /  ^   ^  \
 ( ==  w  == )
  \  ._.  /
   `----' *
  /|    |\
 / |    | \
"""

    SAD = r"""
   /\_____/\
  /  x   x  \
 ( ==  ;  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    LOVE = r"""
   /\_____/\
  /  <   >  \
 ( ==  w  == )
  \  ._.  /
   `----' *
  /|    |\
 / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小鸡 ASCII Art ====================
class ChickASCII:
    """小鸡 ASCII Art - 圆润温暖版"""

    HAPPY = r"""
     _  _
    ( \/ )
    ( o.o )
    (  >  )
   /|    |\
  / |    | \
"""

    THINKING = r"""
     _  _
    ( \/ )
    ( o.o )
    (  ?  )
   /|    |\
  / |    | \
"""

    WORKING = r"""
     _  _
    ( \/ )
    ( *.* )
    (  <  )
   /|    |\
  / |    | \
"""

    SLEEPING = r"""
     _  _
    ( \/ )
    ( -. )
    (  ~  )
   /|    |\
  / |    | \
    zzZ
"""

    SURPRISED = r"""
     _  _
    ( \/ )
    ( O.O )
    (  !  )
   /|    |\
  / |    | \
"""

    SUCCESS = r"""
     _  _
    ( \/ )
    ( ^o^ )
    (  v  )
   /|    |\ *
  / |    | \
"""

    SAD = r"""
     _  _
    ( \/ )
    ( T_T )
    (  .  )
   /|    |\
  / |    | \
"""

    LOVE = r"""
     _  _
    ( \/ )
    ( <3<3)
    (  >  )
   /|    |\ *
  / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 兔兔 ASCII Art ====================
class BunnyASCII:
    """兔兔 ASCII Art - Q 版长耳朵头像"""

    HAPPY = r"""
    /\   /\
   {  `-'  }
   {  o o  }
   ~~>  v <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    THINKING = r"""
    /\   /\
   {  `-'  }
   {  ? ?  }
   ~~>  . <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    WORKING = r"""
    /\   /\
   {  `-'  }
   {  * *  }
   ~~>  < <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    SLEEPING = r"""
    /\   /\
   {  - -  }
   {  - -  }
   ~~>  ~ <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    SURPRISED = r"""
    /\   /\
   {  `-'  }
   {  O O  }
   ~~>  ! <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    SUCCESS = r"""
    /\   /\
   {  `-'  }
   {  ^ ^  }
   ~~>  w <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"` *
"""

    SAD = r"""
    /\   /\
   {  `-'  }
   {  ; ;  }
   ~~>  . <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"`
"""

    LOVE = r"""
    /\   /\
   {  `-'  }
   {  < >  }
   ~~>  w <~~
    \  ===  /
   __`-----'__
  /  /|   |\  \
  `"` `"` `"` `"` *
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 果冻团 ASCII Art ====================
class SlimeASCII:
    """果冻团 ASCII Art - 最稳的 Q 版圆润预设"""

    HAPPY = r"""
      ______
    /  o  o \
   /    --   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    THINKING = r"""
      ______
    /  ?  ? \
   /    ..   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    WORKING = r"""
      ______
    /  *  * \
   /    <<   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    SLEEPING = r"""
      ______
    /  -  - \
   /    ~~   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    SURPRISED = r"""
      ______
    /  O  O \
   /    !!   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    SUCCESS = r"""
      ______
    /  ^  ^ \
   /    ww   \
  |   \____/  |
  |  /_____\  |
   \________/ *
"""

    SAD = r"""
      ______
    /  ;  ; \
   /    ..   \
  |   \____/  |
  |  /_____\  |
   \________/
"""

    LOVE = r"""
      ______
    /  <  > \
   /    ww   \
  |   \____/  |
  |  /_____\  |
   \________/ *
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 企鹅 ASCII Art ====================
class PenguinASCII:
    """企鹅 ASCII Art - 直立 Q 版预设"""

    HAPPY = r"""
      .--.
     |o_o |
     |:_/ |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    THINKING = r"""
      .--.
     |? ? |
     |:./ |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    WORKING = r"""
      .--.
     |* * |
     |:<> |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    SLEEPING = r"""
      .--.
     |-_- |
     |:~  |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    SURPRISED = r"""
      .--.
     |O O |
     |:!: |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    SUCCESS = r"""
      .--.
     |^ ^ |
     |:w: |
    //   \ \
   (|     | )
  /'\_   _/`\ *
  \___)=(___/
"""

    SAD = r"""
      .--.
     |; ; |
     |:.: |
    //   \ \
   (|     | )
  /'\_   _/`\
  \___)=(___/
"""

    LOVE = r"""
      .--.
     |< > |
     |:w: |
    //   \ \
   (|     | )
  /'\_   _/`\ *
  \___)=(___/
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        return _generic_pose_from_status(cls, pose, direction, frame_index)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== Moose ASCII Art ====================
class MooseASCII:
    """Moose ASCII Art - cowsay 风格驼鹿头像"""

    POSE_ART = {
        ("idle", "left"): [
            r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("idle", "right"): [
            r"""
          ^__^
  _______/(oo)
/\/(       (__)
   ||----w |
   ||     ||
""",
        ],
        ("walk", "left"): [
            r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              ||----w |
              //     \\
""",
            r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              //----w |
              ||     \\
""",
        ],
        ("walk", "right"): [
            r"""
          ^__^
  _______/(oo)
/\/(       (__)
   ||----w |
   //     \\
""",
            r"""
          ^__^
  _______/(oo)
/\/(       (__)
   //----w |
   ||     \\
""",
        ],
        ("turn", "left"): [
            r"""
         \  ^__^
          \ (oo)\__
            (__)\  \__
                ||---\_
                ||    ||
""",
            r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("turn", "right"): [
            r"""
       ^__^  /
   __/(oo) /  
__/  /(__)
_/---||
||    ||
""",
            r"""
        ^__^   /
_______/(oo)  / 
/\/(       /(__)
 | w----||
 ||     ||
""",
        ],
        ("think", "left"): [
            r"""
      \   ^__^
       \  (??)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("think", "right"): [
            r"""
          ^__^
  _______/(??)
/\/(       (__)
   ||----w |
   ||     ||
""",
        ],
        ("sleep", "left"): [
            r"""
        zZ ^__^
          (--)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("sleep", "right"): [
            r"""
          ^__^ zZ
  _______/(--)
/\/(       (__)
   ||----w |
   ||     ||
""",
        ],
        ("success", "left"): [
            r"""
      \   ^__^
       \  (^^)\_______
          (__)\       )\/\
              ||----w | *
              //     \\
""",
        ],
        ("success", "right"): [
            r"""
          ^__^
  _______/(^^)
/\/(       (__)
 * ||----w |
   //     \\
""",
        ],
        ("sad", "left"): [
            r"""
      \   ^__^
       \  (;;)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("sad", "right"): [
            r"""
          ^__^
  _______/(;;)
/\/(       (__)
   ||----w |
   ||     ||
""",
        ],
        ("confused", "left"): [
            r"""
      \   ^__^
       \  (OO)\_______
          (__)\   ?   )\/\
              ||----w |
              ||     ||
""",
        ],
        ("confused", "right"): [
            r"""
          ^__^
  _______/(OO)
/\/(  ?    (__)
   ||----w |
   ||     ||
""",
        ],
        ("tired", "left"): [
            r"""
      \   ^__^
       \  (--)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
""",
        ],
        ("tired", "right"): [
            r"""
          ^__^
  _______/(--)
/\/(       (__)
   ||----w |
   ||     ||
""",
        ],
    }

    HAPPY = r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
"""

    THINKING = r"""
      \   ^__^
       \  (??)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
"""

    WORKING = r"""
      \   ^__^
       \  (oo)\_______
          (__)\       )\/\
              //----w |
              ||     \\
"""

    SLEEPING = r"""
        zZ ^__^
          (--)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
"""

    SURPRISED = r"""
      \   ^__^
       \  (OO)\_______
          (__)\   !   )\/\
              ||----w |
              ||     ||
"""

    SUCCESS = r"""
      \   ^__^
       \  (^^)\_______
          (__)\       )\/\
              ||----w | *
              //     \\
"""

    SAD = r"""
      \   ^__^
       \  (;;)\_______
          (__)\       )\/\
              ||----w |
              ||     ||
"""

    LOVE = r"""
      \   ^__^
       \  (<<)\_______
          (__)\  w    )\/\
              ||----w | *
              ||     ||
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_pose_art(
        cls,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        sprites = cls.POSE_ART.get((pose, direction))
        if not sprites:
            sprites = cls.POSE_ART.get(("idle", direction)) or cls.POSE_ART[("idle", "right")]
        index = frame_index % len(sprites)
        return sprites[index]

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 通用 Banner 生成 ====================
def _make_simple_banner(name: str, version: str, pet_data: dict = None) -> str:
    """生成简洁的 Banner（跨终端兼容的 ASCII 边框）"""
    if pet_data is None:
        pet_data = {}

    level = pet_data.get('level', 1)
    mood = pet_data.get('mood', 100)
    hunger = pet_data.get('hunger', 100)
    energy = pet_data.get('energy', 100)
    health = pet_data.get('health', 100)
    love = pet_data.get('love', 100)
    exp = pet_data.get('exp', 0)
    exp_to_next = pet_data.get('exp_to_next', 100)

    age = level - 1

    mood_emoji = "😊" if mood > 70 else "😐" if mood > 40 else "😢"
    hunger_emoji = "🍖" if hunger > 70 else "🍽️" if hunger > 40 else "😫"
    energy_emoji = "⚡" if energy > 70 else "💤" if energy > 40 else "🥱"
    health_emoji = "❤️" if health > 70 else "💔" if health > 40 else "🏥"
    love_emoji = "💕" if love > 70 else "💗" if love > 40 else "💔"

    exp_percent = exp / exp_to_next if exp_to_next > 0 else 0
    exp_bar = "#" * int(exp_percent * 6) + "-" * (6 - int(exp_percent * 6))

    # 使用 ASCII 边框字符，兼容所有终端
    lines = [
        "",
        "  +----------------------------------------------------+",
        "  |  {} {}                                      |".format(name, version),
        "  |  {}心情:{:3}/100  {}饱食:{:3}/100  {}活力:{:3}/100  |".format(
            mood_emoji, mood, hunger_emoji, hunger, energy_emoji, int(energy)),
        "  |  {}健康:{:3}/100  {}爱心:{:3}/100  经验:[{}]  |".format(
            health_emoji, health, love_emoji, love, exp_bar),
        "  |  Lv.{} (年龄:{}岁)                                |".format(level, age),
        "  +----------------------------------------------------+",
        "",
    ]

    return "\n".join(lines)


# ==================== 形象管理器 ====================
class AvatarManager:
    """ASCII 形象管理器"""

    PRESETS: Dict[str, Type] = {
        "lobster": LobsterASCII,
        "shrimp": ShrimpASCII,
        "crab": CrabASCII,
        "cat": CatASCII,
        "chick": ChickASCII,
        "bunny": BunnyASCII,
        "slime": SlimeASCII,
        "penguin": PenguinASCII,
        "moose": MooseASCII,
    }

    PRESET_INFO = {
        "lobster": {"name": "龙虾宝宝", "icon": "🦞", "desc": "经典龙虾形象"},
        "shrimp": {"name": "小虾米", "icon": "🦐", "desc": "Q萌跳跃小虾"},
        "crab": {"name": "小螃蟹", "icon": "🦀", "desc": "简洁卡通螃蟹"},
        "cat": {"name": "猫猫", "icon": "🐱", "desc": "可爱猫猫机器人"},
        "chick": {"name": "小鸡", "icon": "🐣", "desc": "圆润温暖小鸡"},
        "bunny": {"name": "兔兔", "icon": "🐰", "desc": "长耳朵 Q 版头像"},
        "slime": {"name": "果冻团", "icon": "🟢", "desc": "圆润稳定的果冻团"},
        "penguin": {"name": "企鹅", "icon": "🐧", "desc": "直立可爱的企鹅"},
        "moose": {"name": "Moose", "icon": "🫎", "desc": "cowsay 风格驼鹿"},
    }

    def __init__(self, preset: str = "lobster"):
        self.current = self.PRESETS.get(preset, LobsterASCII)
        self.preset_name = preset

    def get_art(self, status: str) -> str:
        """根据状态获取 ASCII Art"""
        return self.current.get_status_art(status)

    def get_pose_art(
        self,
        pose: str,
        direction: str = "right",
        frame_index: int = 0,
        variant: str | None = None,
    ) -> str:
        """根据姿态、朝向与帧索引获取 ASCII Art。"""
        if hasattr(self.current, "get_pose_art"):
            return self.current.get_pose_art(
                pose=pose,
                direction=direction,
                frame_index=frame_index,
                variant=variant,
            )

        pose_to_status = {
            "idle": "happy",
            "walk": "working",
            "turn": "surprised",
            "think": "thinking",
            "sleep": "sleeping",
            "success": "success",
            "sad": "sad",
            "confused": "surprised",
            "tired": "sleeping",
        }
        return self.current.get_status_art(pose_to_status.get(pose, "happy"))

    def get_banner(self, name: str = None, version: str = "v1.0", pet_data: dict = None) -> str:
        """生成 Banner"""
        if name is None:
            name = self.PRESET_INFO.get(self.preset_name, {}).get("name", "Baby")
        return self.current.get_banner(name, version, pet_data)

    def get_welcome_art(self) -> str:
        """获取欢迎 ASCII Art"""
        return self.current.get_welcome_art()

    def switch(self, preset: str) -> bool:
        """切换形象"""
        if preset in self.PRESETS:
            self.current = self.PRESETS[preset]
            self.preset_name = preset
            return True
        return False

    def list_presets(self) -> Dict[str, dict]:
        """列出所有可用形象"""
        return self.PRESET_INFO.copy()


# 全局形象管理器实例
_avatar_manager: AvatarManager = None


def get_avatar_manager(preset: str = None) -> AvatarManager:
    """获取全局形象管理器"""
    global _avatar_manager
    if _avatar_manager is None:
        _avatar_manager = AvatarManager(preset or "lobster")
    elif preset:
        _avatar_manager.switch(preset)
    return _avatar_manager


def get_lobster_banner(name: str = "Baby Claw", version: str = "v1.0", pet_data: dict = None) -> str:
    """生成 Banner（兼容旧接口）"""
    return get_avatar_manager().get_banner(name, version, pet_data)


def get_status_lobster(status: str) -> str:
    """根据状态获取形象（兼容旧接口）"""
    return get_avatar_manager().get_art(status)


# 保留旧的全局常量（兼容）
LOBSTER_HAPPY = LobsterASCII.HAPPY
LOBSTER_THINKING = LobsterASCII.THINKING
LOBSTER_WORKING = LobsterASCII.WORKING
LOBSTER_SLEEPING = LobsterASCII.SLEEPING
LOBSTER_SURPRISED = LobsterASCII.SURPRISED
LOBSTER_SUCCESS = LobsterASCII.SUCCESS
LOBSTER_SAD = LobsterASCII.SAD
LOBSTER_LOVE = LobsterASCII.LOVE
