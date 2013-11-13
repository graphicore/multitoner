Multitoner
==========

Create “Multitone” (Monotone, Duotone,  Tritone, Quadtone, …) EPS-files for printing.

Another short description of what the Multitoner does can be found in
[this blogentry](http://graphicore.de/en/archive/2013-06-13_it-is-a-multitoner)

Multitoner is licensed under the terms of the GPL v3. And comes WITHOUT
ANY WARRANTY. See the file LICENSE.

INSTALL
-------
Please see INSTALL for info on how to get this thing started. Especially
the dependencies are listed there.


RUN
---

When everything is fine $ ./gtk_multitoner.py should launch the
main window of the application. You will either want to create 
a new multitoner project or open the included example file (see below).
I included some tooltips in the GUI so I think you'll find your way around
there just fine.

If you want to experiment with PANTONE color names I found this website
quite helpful: [My Pantone Color](http://www.mypantone.info/) however
print professionals will use a color fan I suppose.

The directory ./example includes 4 files:
  - a screenshot of the multitoner with an opened preview window
  - the multitoner profile file (profile.mtt) that was used in the
    screenshot, the contents are in the JSON format, you can open it in
    a text editor and study its contents
  - the source image opened in in the screenshot (source.png)
  - the resulting eps after exporting the source image (result.eps)


Preview Rendering
-----------------

The Multitoner needs some cpu power to render previews. Especially
big images can be challenging. That is because of the rather complex
process of rendering that is used: A complete EPS file is generated internally
and then passed to the ghostscript engine which renders the previews to
its display callback interface. With a multicore processor you should get
around well. Another option would be to create an mtt file using a shrinked
version of the desired image and then use mtt2eps.py from the commandline
with the real size image:
$ ./mtt2eps.py example/profile.mtt example/source.png example/result_direct.eps


CALL FOR HELP: Color Management
-------------------------------

I choose the process above to have an as accurate as posssible preview
and in the hope that it can get just the best preview possible when
we start using the advanced color management features of Ghostscript.
I'd love to see some help coming from the ghostscript ninjas out there.
A hint for what we want to do can be found in a document called:
"Ghostscript 9.07 Color Management" 
[GS9_Color_Management.pdf](www.ghostscript.com/doc/current/GS9_Color_Management.pdf)
 by  artifex. You can read it up at: section 8.2 "DeviceN Colors"


CREDITS
-------

The Multitoner was initiated by [Silber & Blei](https://silber-und-blei.com)
and its initial development was done by [graphicore](http://graphicore.de)

@ 2013, Lasse Fister Lasse Fister <commander@graphicore.de>

Please report what you experienced with the Multitoner. I'm very curious.

ENJOY!
