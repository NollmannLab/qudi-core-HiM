# Hardware validation test plan

This is a checklist for validating on real hardware the equipment that has been refactored to
qudi-core so far. Mock/unit tests (run during development, see the devlog) check that the code
*logic* is correct; this plan checks that it still behaves correctly when talking to the actual
instrument. Go through it once per equipment after a refactoring round touches that equipment, and
whenever new hardware is connected.

How to use it: work through a section top to bottom, tick each box, and write down anything
unexpected (even if it "worked anyway") next to the item. If a box can't be ticked, that's a bug -
note the exact steps and stop before moving to the next section.

Legend: `[ ]` untested, `[x]` passed, `[!]` failed / unexpected behaviour (add a note).

Last updated: 2026-09-22

---

## Cameras

Applies to: Andor iXon Ultra 888, Photometrics Kinetix, Hamamatsu ORCA-Flash4.0, and the dummy
camera (for exercising the GUI/logic without hardware). Test each physical camera you have
available; skip the ones you don't.

### 1. Activation

- [ ] Camera activates cleanly from a cold start (module `on_activate` with the camera powered on
      and connected).
- [ ] `is_available()` is `True` after a normal activation (check via the GUI: camera appears
      selectable / responsive).
- [ ] Deactivate and reactivate the module without restarting qudi - no crash, no leftover "busy"
      state.
- [ ] **Activation failure is handled gracefully**: physically disconnect the camera (or power it
      off) and activate anyway.
  - [ ] The error is logged, qudi does **not** crash.
  - [ ] If this camera is behind the multi-camera interfuse, the interfuse and the GUI still
        activate normally with the *other* cameras, and the unavailable one is simply absent from
        the camera selector.
  - [ ] If this is the *only* camera, activation of the logic/interfuse fails with a clear error
        message (not a silent hang).
  - [ ] Reconnect the camera and reactivate - it comes back normally.

### 2. Basic acquisition

- [ ] Single-image acquisition (snap) works and displays a sensible image.
- [ ] Live acquisition starts, streams images continuously, and stops cleanly.
- [ ] **Live acquisition, full frame, left running for several minutes** - no crash, no frozen
      image, no dropped connection to the camera. *(This is on the TODO list for the Andor camera
      specifically - see `ixon_ultra_888.py` header.)*
- [ ] Movie/video acquisition of a fixed number of frames completes and all frames are present in
      the saved file.
- [ ] **Movie acquisition, full frame** - same crash/freeze check as live acquisition, full length
      you'd actually use in an experiment, not just a handful of frames.
- [ ] Setting exposure time changes the real acquisition rate/behaviour (sanity check with a
      stopwatch or timestamps, not just that the GUI field accepts the value).
- [ ] Setting gain (on cameras that support it) changes image brightness/noise as expected.
- [ ] Stopping an acquisition mid-way (abort) leaves the camera in a state where you can
      immediately start a new acquisition.

### 3. Region of interest (ROI)

- [ ] Set a ROI smaller than the full sensor - acquired images have the expected reduced size.
- [ ] Go back from a ROI to full frame - no error, image size is back to the full sensor.
- [ ] **Set a second, different ROI right after a first one (without going back to full frame in
      between)** - this used to fail on the Kinetix with "New ROI overlaps existing ROI"; confirm
      it now works cleanly.
- [ ] Live acquisition with a ROI set - runs without crashing (see TODO above: test ROI together
      with live/movie, not only full frame).
- [ ] Movie acquisition with a ROI set - runs without crashing and saved frames have the ROI size.
- [ ] Spooling with a ROI set, if you use spooling on this camera (see Andor-specific section
      below).

### 4. Exposure / cycle time display (GUI)

- [ ] For a camera where the acquisition cycle equals the exposure (Kinetix, ORCA, dummy): the GUI
      exposure field is labelled "Exposure time" and shows the value you set.
- [ ] For the Andor camera: the GUI field switches to "Cycle time" and shows a value slightly
      *longer* than the requested exposure once the kinetic/readout overhead is non-negligible
      (e.g. short exposures, frame-transfer mode). Confirm the displayed number matches what you'd
      expect from the camera's own reported kinetic time, not just the exposure you typed.
- [ ] Saved file metadata contains a cycle-time value (check an OME-TIFF's metadata) for **every**
      camera, not only the Andor one.

### 5. Saving

- [ ] Save a single image / a short movie as OME-TIFF - completes without error, opens correctly in
      Fiji/ImageJ or your usual viewer, timestamps between frames look right.
- [ ] Save as .fits (if used) - completes without error.
- [ ] For non-Andor cameras specifically: confirm OME-TIFF saving no longer raises an error (this
      used to crash before the cycle-time metadata fix).

### 6. Andor iXon Ultra 888 - camera-specific checks

- [ ] Temperature control: setting a target temperature, reading back the current temperature and
      cooler status all work; cooler on/off toggles correctly.
- [ ] Shutter: opens/closes as expected around acquisitions (no image with the shutter unexpectedly
      closed, no shutter left open when it shouldn't be).
- [ ] EM gain: setting a gain value changes the image accordingly; gain limits reported by the GUI
      match the camera's real range.
- [ ] **Spooling - only when you explicitly ask for it**: confirm that starting an acquisition
      normally (live, snap, ordinary movie) never silently switches to spooling.
  - [ ] Explicitly requesting spooling (tif or fits format, display off) starts a spooled
        acquisition and produces a valid file on disk of the expected size/frame count.
  - [ ] Requesting spooling with display **on** correctly falls back to a normal video acquisition
        (this is intentional - spooling + live display doesn't work on this camera).
  - [ ] Spooling combined with a ROI (see section 3) - test explicitly, this combination has not
        been validated yet.
  - [ ] Cancel a spooling acquisition partway through - camera recovers cleanly, no leftover files
        or stuck state.
- [ ] `can_spool` correctly reflects this camera's capability - if you temporarily test with a
      different camera behind the interfuse, spooling options should not be offered for it.
- [ ] Config sanity check: with `temperature_control`, `mechanical_shutter`, `gain_control`, and
      `support_live_acquisition` **left unset** in the config file, confirm the camera behaves as
      if they are all `False` (no temperature UI, no shutter control, no gain UI, no live
      acquisition offered) - this was previously inverted by a config-default bug.

### 7. Multi-camera switching (if more than one camera is configured behind the interfuse)

- [ ] All configured cameras appear in the camera selector.
- [ ] Switching the active camera while idle works and resets exposure, gain, ROI, contrast, and
      the displayed image to that camera's own defaults.
- [ ] Switching is refused (with a clear message, not a silent no-op) while an acquisition is
      running, while saving, or during a synchronized multichannel acquisition.
- [ ] After switching, camera-specific controls (temperature, shutter, gain, spooling) correctly
      show/hide for the newly active camera's capabilities.
- [ ] If one configured camera fails to activate (see section 1), it is absent from the selector
      but the others remain fully usable.

---

## Fluidics (Fluigent)

Applies to: the Fluigent-based fluidics system (SDK module, pump(s), flow sensor), and any pump
running through the generic DAQ-controlled pump module (see also the DAQ section below for that
part).

### 1. Activation

- [ ] Fluigent SDK module initializes and discovers the connected hardware (pressure controller,
      flow sensor) without error.
- [ ] Pump module and flow-sensor module both activate independently and report a connected state.
- [ ] Deactivate and reactivate - SDK shuts down and reinitializes cleanly, no leftover handle
      preventing a second activation (check adapter cleanup specifically, since this was fixed
      recently).

### 2. Pump control

- [ ] Setting a pressure/flow setpoint on the main fluidics pump produces the expected physical
      response (observe the flow sensor reading change accordingly).
- [ ] The rinsing pump (now a generic pump rather than an application-specific module) responds
      correctly to on/off and setpoint commands.
- [ ] If you run the main pump and the rinsing pump at the same time, they don't interfere with
      each other (each is its own module instance).
- [ ] PID flow regulation (in the fluidics logic) reaches and holds the target flow rate, using
      whichever pump backend is configured (Fluigent pressure controller or DAQ-controlled pump).

### 3. Flow sensor

- [ ] Flow sensor readings update continuously and match a rough sanity check (e.g. zero flow when
      the pump is off).
- [ ] Channel normalization: if your config specifies channels in a non-default way (names, units,
      indices), confirm the correct physical channel is actually being read - this was an area
      with a recent fix.

### 4. Valves

- [ ] Selecting a valve and a position in the GUI switches the correct physical valve to the
      correct position (double-check with more than one valve configured - the combobox callback
      that ties valve number to position was recently fixed).
- [ ] Rapidly switching between several valves in sequence - each one ends up in the intended
      final position (no cross-talk between the valve number and position selectors).

### 5. End-to-end

- [ ] Run a short, realistic fluidics protocol (e.g. one buffer exchange cycle) start to finish and
      confirm timing/volumes look right.
- [ ] Interrupt a running protocol (stop button) - pumps stop, valves stay in a safe state, and the
      module can be restarted afterwards without reactivating qudi.

---

## DAQ (MCC USB-3104)

Applies to: any logic/hardware that goes through the generic named-channel DAQ interface -
currently the DAQ-controlled pump(s) and any other analog/digital channels you have configured
through it.

### 1. Activation

- [ ] DAQ module activates and lists the configured channels without error.
- [ ] Channel ranges specified in the config file are parsed correctly regardless of the format you
      used (numeric bounds vs. named range) - confirm the *actual* output voltage/range matches
      what you configured, not just that activation succeeded.

### 2. Analog output channels

- [ ] Writing a value to one analog-output channel produces the correct voltage/current at that
      physical channel (check with a multimeter or the downstream device's own reading).
- [ ] **With two or more analog-output channels that share the same DAQ subsystem**: write to each
      one independently and confirm they don't affect each other's output (this exact scenario had
      a bug that was fixed).
- [ ] Reading back a channel's last written value (if used) matches what was actually written.

### 3. DAQ-controlled pump(s)

- [ ] A single DAQ-controlled pump responds correctly to setpoint commands.
- [ ] **Two pumps configured on the same DAQ, on different named channels**: drive both at
      different setpoints at the same time and confirm each pump gets its own, correct signal (no
      channel mix-up between the two pump instances).

### 4. Cleanup

- [ ] Deactivating the DAQ module (or qudi as a whole) leaves all outputs in a safe/expected state
      (e.g. pump outputs back to zero, not left at their last value) - channel cleanup on
      deactivation was recently touched.
- [ ] Reactivating afterwards re-initializes all channels correctly (no channel left registered
      twice, no stale handle).

---

## Pipetting robot

Applies to: the generic pipetting-robot interfuse, on whichever stage backend you're currently
running (PI, ASI MS2000, or dummy for a dry run).

### 1. Activation and homing/calibration

- [ ] Robot activates and, if automatic calibration is configured, calibrates safely: **Z axis
      calibrates before the horizontal axes** (confirm by watching it - Z should move to a safe
      position/finish its own calibration first, horizontal moves only start afterwards).
- [ ] Axis and movement-limit validation rejects an out-of-range target (send a move command beyond
      the configured limits from the GUI/console and confirm it's refused with a clear error, not
      silently clamped or - worse - executed).

### 2. Safe movement pattern

- [ ] Any horizontal move is preceded by Z moving to the configured safe position first (watch a
      full move cycle: Z up/safe -> XY move -> Z down to working position). This should hold for
      moves between tubes, not just the first move after activation.
- [ ] Manually trigger a move to a tube position on the far side of the grid from the current
      position - confirm the robot does not cut through/collide with anything in between (i.e. the
      safe-Z pattern actually protects the intended path).

### 3. Geometry and tube mapping

- [ ] For a Cartesian setup: moving to each corner/edge of the configured tube grid lands on the
      physically correct tube.
- [ ] For a polar setup (if used): angle/radius moves land on the correct tube; check especially
      tubes near the extremes of the angular range.
- [ ] Tube-position mapping is consistent between the GUI's tube identifiers and the physical tube
      that actually gets visited - spot-check a handful of tubes across the grid, not just tube #1.

### 4. Parking

- [ ] Manually parking the robot moves it to the configured safe position via the same safe-Z
      pattern (Z first).
- [ ] If automatic parking on deactivation is enabled in the config: deactivate the module mid-way
      through normal use (not already parked) and confirm it parks safely before shutting down.
- [ ] If automatic parking is disabled: confirm deactivation does **not** move the robot
      unexpectedly.

### 5. Backend swap sanity check (only if you actually switch backends)

- [ ] Switching the configured stage backend (PI <-> ASI MS2000 <-> dummy) requires no changes
      beyond the config file - the pipetting-robot-level behaviour (safety, geometry, tube mapping)
      is identical regardless of which stage is underneath.

---

## After testing

- Note failures directly in this file (change `[ ]` to `[!]` with a short note) or tell me about
  them so I can update the devlog and fix the code - whichever is easier for you.
- Once a section is fully green, we can add a short note in the devlog that it was validated on
  real hardware, with the date.
