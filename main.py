from diagnostics import start_diagnostics, stop_diagnostics, record_issue
import sys


def main():
    diagnostics = start_diagnostics()
    clean = False
    try:
        # Install diagnostics before importing GUI/network dependencies.
        from app import App
        app = App()
        if not diagnostics.available:
            app.log('Diagnostic logging is unavailable. Check local folder permissions.')
            app.progress_label.configure(text='Diagnostic logging unavailable · Check permissions')
        elif diagnostics.previous_unclean:
            app.log('The previous run ended without a normal close. Check Activity → Log → Open diagnostics.')
            app.progress_label.configure(text='Previous run ended unexpectedly · Check diagnostic logs')
        app.mainloop()
        clean = bool(getattr(app, '_normal_close_requested', False))
        if not clean:
            record_issue('unexpected_mainloop_return', level='WARNING')
        return 0 if clean else 1
    except KeyboardInterrupt as error:
        record_issue('application_interrupted', error, level='WARNING')
        return 130
    except Exception as error:
        record_issue('application_failed', error)
        sys.stderr.write('Application stopped unexpectedly. Check the private diagnostic logs.\n')
        return 1
    finally:
        stop_diagnostics(clean=clean)


if __name__ == '__main__':
    raise SystemExit(main())
