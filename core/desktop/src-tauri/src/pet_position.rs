//! Pure desktop Pet placement math.
//!
//! Keeping the monitor-boundary calculation independent from Tauri makes the
//! edge cases testable without opening a Windows window.

pub(crate) fn anchored_overlay_position(
    desired_x: i64,
    desired_y: i64,
    pet_left: i64,
    monitor_left: i64,
    monitor_top: i64,
    monitor_right: i64,
    monitor_bottom: i64,
    overlay_width: i64,
    overlay_height: i64,
) -> (i64, i64) {
    let left_of_pet = pet_left - overlay_width - 8;
    let max_x = (monitor_right - overlay_width).max(monitor_left);
    let max_y = (monitor_bottom - overlay_height).max(monitor_top);
    let x = if desired_x + overlay_width <= monitor_right {
        desired_x
    } else if left_of_pet >= monitor_left {
        left_of_pet
    } else {
        desired_x.clamp(monitor_left, max_x)
    };
    let y = desired_y.clamp(monitor_top, max_y);
    (x, y)
}

#[cfg(test)]
mod tests {
    use super::anchored_overlay_position;

    #[test]
    fn prefers_the_right_side_when_it_fits() {
        assert_eq!(
            anchored_overlay_position(200, 100, 200, 0, 0, 1200, 800, 300, 400),
            (200, 100)
        );
    }

    #[test]
    fn flips_to_the_left_when_the_right_side_is_outside() {
        assert_eq!(
            anchored_overlay_position(1100, 100, 1100, 0, 0, 1200, 800, 300, 400),
            (792, 100)
        );
    }

    #[test]
    fn clamps_when_neither_side_has_room() {
        assert_eq!(
            anchored_overlay_position(10, -40, 10, 0, 0, 200, 100, 300, 400),
            (0, 0)
        );
    }
}
