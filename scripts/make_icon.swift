// Original code-drawn artwork. No remote fonts, images or dependencies.
import AppKit

guard CommandLine.arguments.count == 2 else {
    fatalError("Usage: swift scripts/make_icon.swift assets/now-cleaner.png")
}
let size = CGFloat(1024)
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()
func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat) -> NSColor {
    NSColor(srgbRed: red, green: green, blue: blue, alpha: 1)
}
func card(_ x: CGFloat, _ y: CGFloat, _ width: CGFloat, _ height: CGFloat, _ radius: CGFloat, _ fill: NSColor) {
    fill.setFill()
    NSBezierPath(roundedRect: NSRect(x: x, y: y, width: width, height: height), xRadius: radius, yRadius: radius).fill()
}
let tile = NSBezierPath(roundedRect: NSRect(x: 64, y: 64, width: 896, height: 896), xRadius: 202, yRadius: 202)
NSGradient(starting: color(0.12, 0.43, 0.38), ending: color(0.045, 0.23, 0.22))!.draw(in: tile, angle: -65)
// Offset pages make a recognisable organised-document silhouette at Dock sizes.
card(302, 220, 456, 548, 44, color(0.28, 0.58, 0.50))
card(258, 252, 456, 548, 44, color(0.61, 0.78, 0.68))
card(214, 284, 456, 548, 44, color(0.96, 0.97, 0.92))
card(282, 685, 250, 24, 12, color(0.18, 0.37, 0.32))
card(282, 627, 312, 18, 9, color(0.68, 0.76, 0.69))
card(282, 578, 235, 18, 9, color(0.68, 0.76, 0.69))
color(0.045, 0.27, 0.23).setFill()
NSBezierPath(ovalIn: NSRect(x: 518, y: 214, width: 270, height: 270)).fill()
let check = NSBezierPath()
check.move(to: NSPoint(x: 586, y: 353))
check.line(to: NSPoint(x: 635, y: 307))
check.line(to: NSPoint(x: 719, y: 399))
check.lineWidth = 25
check.lineCapStyle = .round
check.lineJoinStyle = .round
color(0.79, 0.93, 0.65).setStroke()
check.stroke()
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
