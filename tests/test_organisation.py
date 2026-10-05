import unittest
from now_cleaner.organisation import organise, folder_name


class OrganisationTests(unittest.TestCase):
    def test_only_clear_week_names_are_normalised(self):
        self.assertEqual(folder_name('week_2'), 'Week 02')
        self.assertEqual(folder_name('Week 3 - Discovery'), 'Week 03 - Discovery')
        self.assertEqual(folder_name('MBS Discover'), 'MBS Discover')
        self.assertEqual(folder_name('Weekly help'), 'Weekly help')
        self.assertEqual(folder_name('Week 1a'), 'Week 1a')

    def test_file_folder_conflicts_do_not_overwrite(self):
        files = {'a': {'path': 'Help'}, 'b': {'path': 'Help/Contact.txt'}}
        organise(files)
        self.assertNotEqual(files['a']['course_path'], files['b']['course_path'].split('/')[0])

    def test_assigned_paths_take_priority_over_new_files(self):
        files = {'b': {'path': 'Week 1/Notes.txt', 'course_path': 'Week 01/Notes.txt'},
                 'a': {'path': 'Week 01/Notes.txt'}}
        organise(files)
        self.assertEqual(files['b']['course_path'], 'Week 01/Notes.txt')
        self.assertNotEqual(files['a']['course_path'], files['b']['course_path'])

    def test_unsafe_saved_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            organise({'a': {'path': 'notes.txt', 'course_path': '../outside.txt'}})
