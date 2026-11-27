import AppKit
import WebKit

// usage: webkit_check <page.html> <width>   prints the text of #lb-check
let arguments = CommandLine.arguments
let width = Double(arguments[2])!
let page = try! String(contentsOfFile: arguments[1], encoding: .utf8)
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: 900))
let window = NSWindow(contentRect: web.frame, styleMask: [.borderless], backing: .buffered, defer: false)
window.contentView = web
web.loadHTMLString(page, baseURL: nil)
func poll(_ remaining: Int) {
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
        web.evaluateJavaScript("(document.getElementById('lb-check')||{}).textContent||''") { value, _ in
            if let text = value as? String, !text.isEmpty { print(text); exit(0) }
            if remaining == 0 { exit(1) }
            poll(remaining - 1)
        }
    }
}
poll(80)
app.run()
