#define Uses_TKeys
#define Uses_TApplication
#define Uses_TEvent
#define Uses_TRect
#define Uses_TDialog
#define Uses_TStaticText
#define Uses_TButton
#define Uses_TMenuBar
#define Uses_TSubMenu
#define Uses_TMenuItem
#define Uses_TStatusLine
#define Uses_TStatusItem
#define Uses_TStatusDef
#define Uses_TDeskTop

#include <tvision/tv.h>

class TVimApp : public TApplication {

public:
  TVimApp();

  virtual void handleEvent(TEvent &event);
  static TMenuBar *initMenuBar(TRect);
  static TStatusLine *initStatusLine(TRect);
};

TVimApp::TVimApp()
    : TProgInit(&TVimApp::initStatusLine, &TVimApp::initMenuBar,
                &TVimApp::initDeskTop) {}

void TVimApp::handleEvent(TEvent &event) {
  TApplication::handleEvent(event);
  if (event.what == evCommand) {
    switch (event.message.command) {
    default:
      break;
    }
  }
}

TMenuBar *TVimApp::initMenuBar(TRect r) {

  r.b.y = r.a.y + 1;

  return new TMenuBar(
      r, *new TSubMenu("~F~ile", kbAltF) +
             *new TMenuItem("E~x~it", cmQuit, cmQuit, hcNoContext, "Alt-X"));
}

TStatusLine *TVimApp::initStatusLine(TRect r) {
  r.a.y = r.b.y - 1;
  return new TStatusLine(r,
                         *new TStatusDef(0, 0xFFFF) +
                             *new TStatusItem("~Alt-X~ Exit", kbAltX, cmQuit) +
                             *new TStatusItem(0, kbF10, cmMenu));
}

int main() {
  TVimApp vim_app;
  vim_app.run();
  return 0;
}
