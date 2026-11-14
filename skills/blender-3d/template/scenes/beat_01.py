"""Beat 1 (product): the robot alone on the sweep. A slow push in, the robot turns to camera."""
import cast
import studio as S

CM = S.CM


def build(ctx):
    L = ctx.look
    L.rig(height=45 * CM)
    cam = L.shot(height=45 * CM, azimuth=-18)
    bot = cast.toy_robot(S, "rex")
    S.key(bot, 0.0, rotation=(0, 0, -25))
    S.key(bot, ctx.seconds, rotation=(0, 0, 0))
    S.aim(cam, 0.0)
    S.aim(cam, ctx.seconds, location=tuple(cam.location * 0.92), target=(0, 0, 24 * CM))
