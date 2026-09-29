"""Conservative boot-config inspection for the Pi Zero installer."""


def zero_dwc2_overlays(text):
    """Yield (line index, directive) unless a model filter excludes Pi Zero.

    Unknown filters remain subject to validation. Other filter types do not
    reset a model filter; [all] resets every filter.
    """
    excluded_models = {'pi2', 'pi3', 'pi3+', 'pi4', 'pi400', 'pi5',
                       'pi500', 'pi500+', 'cm4', 'cm4s', 'cm5'}
    excluded = False
    for index, line in enumerate(text.splitlines()):
        directive = line.split('#', 1)[0].strip()
        if directive.startswith('[') and directive.endswith(']'):
            section = directive[1:-1]
            if section in excluded_models:
                excluded = True
            elif section in {'all', 'pi0', 'pi0w', 'pi02', 'pi1'}:
                excluded = False
        if not excluded and directive.startswith('dtoverlay=dwc2'):
            yield index, directive
