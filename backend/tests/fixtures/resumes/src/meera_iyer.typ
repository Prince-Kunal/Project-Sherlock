// Fictional fixture resume in a "designed" style: letter-spaced title, heavy bullet glyphs,
// "GitHub ↗" links hiding their targets, publications section, education last.
#set page(paper: "a4", margin: (x: 0.6in, y: 0.5in))
#set text(font: "Libertinus Serif", size: 9.5pt)
#set par(spacing: 0.5em, leading: 0.45em)
#set list(marker: [●])
#let sec(title) = block(above: 0.8em, below: 0.35em)[#text(size: 11pt, weight: "bold", upper(title)) #v(-0.7em) #line(length: 100%, stroke: 0.8pt)]
#let role(left, right) = grid(columns: (1fr, auto), text(weight: "bold", left), text(style: "italic", weight: "bold", right))

#align(center)[
  #text(size: 20pt, weight: "bold")[MEERA IYER] \
  #text(size: 10pt, tracking: 2pt, weight: "bold")[ROBOTICS & AI DEVELOPER] \
  meera.iyer\@example.com | +91 90000 22222 | Bengaluru, India |
  #link("https://www.linkedin.com/in/meera-iyer-robotics")[linkedin.com/in/meera-iyer-robotics] |
  #link("https://github.com/meeraiyer")[github.com/meeraiyer]
]

#sec[Work Experience]
#role[Robotics Software Intern – Example Automation Labs][Mar 2026 – Jul 2026]
- Developed computer-vision checks for a packaging line that cut mis-labelled boxes by 40%.
- Built a digital-twin dashboard showing live robot cell status for floor supervisors.
- Researched predictive-maintenance signals for industrial arms using vibration data.

#role[PLC Programming Intern – Example Industrial Training Centre][Aug 2025 – Feb 2026]
- Programmed and tested PLC ladder logic for 4 automation rigs, including a conveyor sorter and a press.
- Wrote technical documentation and test reports for each completed rig.

#sec[Projects]
#role[Warehouse Picker Arm Simulation #link("https://github.com/meeraiyer/picker-sim")[GitHub ↗]][Oct 2025 – Dec 2025]
#text(style: "italic")[Isaac Sim · Python · ROS 2]
- Simulated a 7-DoF arm picking mixed items from bins, controlled by a custom Python ROS 2 node.
- Implemented joint-space control and gripper sequencing with a 94% pick success rate in simulation.

#role[Ship Detection in Satellite Images #link("https://github.com/meeraiyer/ship-detect")[GitHub ↗]][Jun 2026 – Jul 2026]
#text(style: "italic")[PyTorch · Object Detection · OpenCV]
- Trained an oriented object detector on aerial imagery and evaluated it with mAP, precision and recall.

#sec[Publications]
#role[Stability-Aware Grasp Planning for Mobile Manipulators in MuJoCo][2026]
#text(style: "italic")[Example International Robotics Conference (ExRC 2026) · Paper ID: EXRC-2026-0417]
- First-author paper proposing a MuJoCo framework that adds centre-of-mass constraints to grasp planning, improving task success over a baseline controller.

#sec[Technical Skills]
#table(columns: (auto, 1fr), stroke: none, inset: 1.5pt,
  [*Languages*], [: Python, C++, C\#],
  [*AI / ML*], [: Deep Learning, Machine Learning, Computer Vision],
  [*Robotics*], [: ROS 2, NVIDIA Isaac Sim, MuJoCo, OpenCV, Linux],
  [*Automation*], [: PLC Programming, Pneumatics],
  [*Tools*], [: Git, GitHub, Docker],
)

#sec[Education]
#role[Example University of Technology, Bengaluru, India][Aug 2024 – Present]
#text(style: "italic")[B.Tech in Robotics and Artificial Intelligence] | *CGPA: 8.91 / 10.0*

#role[Example PU College, Bengaluru, India][Jun 2022 – May 2024]
#text(style: "italic")[Higher Secondary Education — Physics, Chemistry, Mathematics, Computer Science] | *Percentage: 94.2%*
